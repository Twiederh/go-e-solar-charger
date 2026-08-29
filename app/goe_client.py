"""Client for the go-eCharger local API v2 (plain HTTP, no auth by default).

Field names and status codes below are taken from the vendor's own
documentation: https://github.com/goecharger/go-eCharger-API-v2
(API_KEYS_FIRMWARE/apikeys-en.md).
"""
import json
import logging
from typing import Dict, Optional

import requests

logger = logging.getLogger("uvicorn.error")

TIMEOUT = 10

# "car" key: carState, null on internal error.
CAR_STATUS = {
    0: "Unbekannt / Fehler",
    1: "Bereit, kein Auto verbunden",
    2: "Laedt",
    3: "Wartet auf Fahrzeug",
    4: "Ladevorgang beendet",
    5: "Fehler",
}

# "err" key, None means no error.
ERROR_CODES = {
    1: "Fehlerstrom (AC)",
    2: "Fehlerstrom (DC)",
    3: "Phasenfehler",
    4: "Ueberspannung",
    5: "Ueberstrom",
    6: "Diode defekt",
    7: "PP-Signal ungueltig",
    8: "Erdung ungueltig",
    9: "Schuetz haengt fest",
    10: "Schuetz fehlt",
    11: "Fehlerstromsensor unbekannt",
    12: "Unbekannt",
    13: "Uebertemperatur",
    14: "Keine Kommunikation",
    15: "Verriegelung blockiert (offen)",
    16: "Verriegelung blockiert (zu)",
}

# Index of the "Total" active power entry inside the "nrg" array:
# U(L1,L2,L3,N) I(L1,L2,L3) P(L1,L2,L3,N,Total) pf(L1,L2,L3,N)
_NRG_TOTAL_POWER_INDEX = 11


class GoEClient:
    def __init__(self, host: str, api_key: str = ""):
        self.host = host
        self.api_key = api_key

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def push_pv_values(self, solar_w: float, grid_w: float, battery_w: float) -> None:
        """Feeds current PV-surplus-charging input values (Watts) into the
        charger, replacing what pwPlugin used to send directly."""
        ids = json.dumps({"pPv": solar_w, "pGrid": grid_w, "pAkku": battery_w})
        response = requests.get(
            f"http://{self.host}/api/set",
            params={"ids": ids},
            headers=self._headers(),
            timeout=TIMEOUT,
        )
        response.raise_for_status()

    def get_status(self) -> Dict[str, Optional[object]]:
        keys = "car,alw,amp,acu,err,nrg,wh,modelStatus"
        response = requests.get(
            f"http://{self.host}/api/status",
            params={"filter": keys},
            headers=self._headers(),
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()

        nrg = data.get("nrg") or []
        power_w = nrg[_NRG_TOTAL_POWER_INDEX] if len(nrg) > _NRG_TOTAL_POWER_INDEX else None

        car_code = data.get("car")
        err_code = data.get("err")

        return {
            "car_code": car_code,
            "car_text": CAR_STATUS.get(car_code, f"Unbekannter Status ({car_code})"),
            "connected": car_code in (2, 3, 4),
            "charging": car_code == 2,
            "power_w": power_w,
            "allowed": data.get("alw"),
            "allowed_current_a": data.get("acu"),
            "requested_current_a": data.get("amp"),
            "error_code": err_code,
            "error_text": ERROR_CODES.get(err_code) if err_code else None,
            "energy_session_wh": data.get("wh"),
        }
