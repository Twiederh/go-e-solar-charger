"""go-e-solar-charger dashboard.

Background thread: periodically reads power values from the Powerwall
Gateway and pushes them to the go-e Charger's PV-surplus-charging input
(this replaces what the old pwPlugin-based script did), and separately
polls the charger's own status for display.

Web UI:
  GET  /            dashboard with live Powerwall + go-e values
  GET  /api/data    JSON snapshot used by the dashboard's auto-refresh
  GET  /config      form to enter Powerwall / go-e host + credentials
  POST /config      saves the form (persisted in DATA_DIR, see config_store.py)
  POST /config/test one-off connection test for the values in the form,
                     without saving them
"""
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import config_store
from goe_client import GoEClient
from powerwall_client import PowerwallAuthError, PowerwallClient

logger = logging.getLogger("uvicorn.error")

BASE_DIR = os.path.dirname(__file__)

_state_lock = threading.Lock()
_state = {
    "powerwall": None,
    "goe": None,
    "last_success": None,
    "last_attempt": None,
    "error": None,
}


def _poll_loop() -> None:
    pw_client: Optional[PowerwallClient] = None
    pw_signature = None

    while True:
        cfg = config_store.load()
        interval = cfg.get("poll_interval_seconds") or 10

        try:
            if not cfg["powerwall_host"] or not cfg["powerwall_password"]:
                raise RuntimeError(
                    "Powerwall ist noch nicht konfiguriert - siehe /config"
                )

            signature = (
                cfg["powerwall_host"],
                cfg["powerwall_email"],
                cfg["powerwall_password"],
                cfg["timezone"],
            )
            if pw_client is None or signature != pw_signature:
                pw_client = PowerwallClient(
                    cfg["powerwall_host"],
                    cfg["powerwall_email"],
                    cfg["powerwall_password"],
                    cfg["timezone"],
                )
                pw_signature = signature

            power = pw_client.get_power()
            soe = pw_client.get_soe()
            powerwall_data = {**power, "soe_percent": soe}

            goe_data = None
            if cfg["goe_host"]:
                goe_client = GoEClient(cfg["goe_host"], cfg["goe_api_key"])
                try:
                    goe_client.push_pv_values(
                        power["solar_w"], power["grid_w"], power["battery_w"]
                    )
                except Exception as exc:  # noqa: BLE001
                    # Don't let a go-e hiccup hide otherwise-good Powerwall data.
                    logger.warning("Konnte PV-Werte nicht an go-e senden: %s", exc)
                goe_data = goe_client.get_status()

            with _state_lock:
                _state["powerwall"] = powerwall_data
                _state["goe"] = goe_data
                _state["last_success"] = datetime.now().isoformat(timespec="seconds")
                _state["error"] = None

        except PowerwallAuthError as exc:
            pw_client = None  # force a fresh login attempt next cycle
            with _state_lock:
                _state["error"] = str(exc)
        except Exception as exc:  # noqa: BLE001 - this loop must never die
            logger.warning("Poll-Zyklus fehlgeschlagen: %s", exc)
            with _state_lock:
                _state["error"] = str(exc)
        finally:
            with _state_lock:
                _state["last_attempt"] = datetime.now().isoformat(timespec="seconds")

        time.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    thread = threading.Thread(target=_poll_loop, daemon=True, name="poll-loop")
    thread.start()
    yield


app = FastAPI(title="go-e-solar-charger", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    with _state_lock:
        state = dict(_state)
    return templates.TemplateResponse(request, "dashboard.html", {"state": state})


@app.get("/api/data")
def api_data():
    with _state_lock:
        return dict(_state)


@app.get("/config", response_class=HTMLResponse)
def config_form(request: Request, saved: Optional[str] = None):
    cfg = config_store.load()
    view = {
        **cfg,
        "powerwall_password": "",
        "powerwall_password_set": bool(cfg["powerwall_password"]),
        "goe_api_key": "",
        "goe_api_key_set": bool(cfg["goe_api_key"]),
    }
    return templates.TemplateResponse(
        request, "config.html", {"cfg": view, "saved": saved, "test_result": None}
    )


@app.post("/config", response_class=HTMLResponse)
def config_save(
    powerwall_host: str = Form(""),
    powerwall_email: str = Form(""),
    powerwall_password: str = Form(""),
    goe_host: str = Form(""),
    goe_api_key: str = Form(""),
    poll_interval_seconds: int = Form(10),
    timezone: str = Form("Europe/Berlin"),
):
    config_store.update(
        {
            "powerwall_host": powerwall_host.strip(),
            "powerwall_email": powerwall_email.strip(),
            "powerwall_password": powerwall_password,
            "goe_host": goe_host.strip(),
            "goe_api_key": goe_api_key.strip(),
            "poll_interval_seconds": max(2, poll_interval_seconds),
            "timezone": timezone.strip() or "Europe/Berlin",
        }
    )
    return RedirectResponse(url="/config?saved=1", status_code=303)


@app.post("/config/test")
def config_test(
    powerwall_host: str = Form(""),
    powerwall_email: str = Form(""),
    powerwall_password: str = Form(""),
    goe_host: str = Form(""),
    goe_api_key: str = Form(""),
):
    """Tries the given values immediately without saving them - lets you
    verify credentials before committing to them."""
    stored = config_store.load()
    result = {}

    if powerwall_host:
        pw = powerwall_password or stored["powerwall_password"]
        try:
            client = PowerwallClient(powerwall_host, powerwall_email, pw)
            power = client.get_power()
            result["powerwall"] = {"ok": True, "detail": power}
        except Exception as exc:  # noqa: BLE001
            result["powerwall"] = {"ok": False, "detail": str(exc)}

    if goe_host:
        key = goe_api_key or stored["goe_api_key"]
        try:
            client = GoEClient(goe_host, key)
            status = client.get_status()
            result["goe"] = {"ok": True, "detail": status}
        except Exception as exc:  # noqa: BLE001
            result["goe"] = {"ok": False, "detail": str(exc)}

    return JSONResponse(result)
