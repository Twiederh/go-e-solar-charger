"""Client for the local Tesla Powerwall Gateway REST API.

This is not an API Tesla documents publicly - the endpoints and field
names here are reverse-engineered and maintained by the community. This
client follows the same request shapes used by the well-established
https://github.com/jasonacox/pypowerwall and
https://github.com/vloschiavo/powerwall2 projects:

- POST /api/login/Basic with a form body of
  {"username": "customer", "password": <gateway password>,
   "email": <email>, "clientInfo": {"timezone": ...}}
- The gateway replies with either an "AuthCookie"/"UserRecord" cookie pair
  or (depending on firmware) a JSON {"token": ...} used as
  "Authorization: Bearer <token>". This client tries cookie mode first and
  falls back to token mode automatically.
- GET /api/meters/aggregates returns instantaneous power (Watts) nested as
  {"solar": {"instant_power": ...}, "site": {...}, "battery": {...},
   "load": {...}}. "site" is grid power (positive = importing from the
   grid), "battery" is positive while discharging.
- GET /api/system_status/soe returns {"percentage": <battery charge %>}.

This has not been tested against a real Powerwall gateway - please verify
against yours and report back if a firmware version behaves differently.
"""
import logging
import threading
from typing import Dict, Optional

import requests
import urllib3

# The gateway serves a self-signed certificate; there is no way to
# validate it without pinning the device's own cert, so we disable the
# warning the same way the community tools above do.
urllib3.disable_warnings()

logger = logging.getLogger("uvicorn.error")

TIMEOUT = 10


class PowerwallAuthError(Exception):
    """Login to the gateway was rejected - almost always a wrong password."""


class PowerwallClient:
    def __init__(self, host: str, email: str, password: str, timezone: str = "Europe/Berlin"):
        self.host = host
        self.email = email
        self.password = password
        self.timezone = timezone
        self._session = requests.Session()
        self._auth_cookies: Dict[str, str] = {}
        self._auth_header: Dict[str, str] = {}
        self._logged_in = False
        # Guards login + request so two threads never race on the shared
        # session's auth state.
        self._lock = threading.Lock()

    def _login(self) -> None:
        url = f"https://{self.host}/api/login/Basic"
        payload = {
            "username": "customer",
            "password": self.password,
            "email": self.email,
            "clientInfo": {"timezone": self.timezone},
        }
        try:
            response = self._session.post(url, data=payload, verify=False, timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise PowerwallAuthError(
                f"Powerwall {self.host} nicht erreichbar: {exc}"
            ) from exc

        if response.status_code in (401, 403):
            raise PowerwallAuthError(
                f"Anmeldung an der Powerwall {self.host} abgelehnt - Zugangsdaten pruefen"
            )
        response.raise_for_status()

        self._auth_cookies = {}
        self._auth_header = {}
        cookie = response.cookies.get("AuthCookie")
        if cookie:
            self._auth_cookies = {
                "AuthCookie": cookie,
                "UserRecord": response.cookies.get("UserRecord", ""),
            }
        else:
            token = (response.json() or {}).get("token")
            if not token:
                raise PowerwallAuthError(
                    f"Login an der Powerwall {self.host} lieferte weder Cookie noch Token"
                )
            self._auth_header = {"Authorization": f"Bearer {token}"}
        self._logged_in = True
        logger.info("Bei Powerwall %s angemeldet", self.host)

    def _get(self, path: str) -> dict:
        with self._lock:
            if not self._logged_in:
                self._login()

            url = f"https://{self.host}{path}"
            response = self._session.get(
                url,
                cookies=self._auth_cookies,
                headers=self._auth_header,
                verify=False,
                timeout=TIMEOUT,
            )
            if response.status_code in (401, 403):
                # Session likely expired - log in once more before giving up.
                self._logged_in = False
                self._login()
                response = self._session.get(
                    url,
                    cookies=self._auth_cookies,
                    headers=self._auth_header,
                    verify=False,
                    timeout=TIMEOUT,
                )
            response.raise_for_status()
            return response.json()

    def get_power(self) -> Dict[str, float]:
        """Instantaneous power in Watts for solar, grid, battery and house load."""
        data = self._get("/api/meters/aggregates")
        return {
            "solar_w": data["solar"]["instant_power"],
            "grid_w": data["site"]["instant_power"],
            "battery_w": data["battery"]["instant_power"],
            "load_w": data["load"]["instant_power"],
        }

    def get_soe(self) -> Optional[float]:
        """Battery state of charge in percent, or None if the call fails."""
        try:
            return self._get("/api/system_status/soe")["percentage"]
        except Exception as exc:  # noqa: BLE001 - this is a best-effort extra
            logger.debug("Konnte Ladezustand nicht lesen: %s", exc)
            return None
