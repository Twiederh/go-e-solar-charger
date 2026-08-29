"""Persisted configuration for the dashboard.

Values entered on the /config page (Powerwall and go-e credentials, poll
interval, ...) are stored as JSON in DATA_DIR so they survive container
restarts. The directory is meant to be mounted as a Docker volume (see
docker-compose.yml) and must never be committed to git - it holds the
Powerwall password and, optionally, a go-e API key in plain text.
"""
import json
import os
import threading
from typing import Any, Dict

# Reentrant because load() calls save() (via _ensure_file) while already
# holding the lock.
_LOCK = threading.RLock()

DATA_DIR = os.environ.get("DATA_DIR", "/code/data")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")

# Secrets are never defaulted from here; GoE/TZ are seeded from the
# environment once, purely to ease the upgrade from the old env-var-only
# setup. Env vars are ignored after the config file exists.
DEFAULTS: Dict[str, Any] = {
    "powerwall_host": "",
    "powerwall_email": "",
    "powerwall_password": "",
    "goe_host": os.environ.get("GoE", ""),
    "goe_api_key": "",
    "poll_interval_seconds": 10,
    "timezone": os.environ.get("TZ", "Europe/Berlin"),
}

# Config keys that hold secrets. Used by the /config page to avoid ever
# echoing a stored value back into the HTML form.
SECRET_KEYS = ("powerwall_password", "goe_api_key")


def _ensure_file() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(CONFIG_PATH):
        save(dict(DEFAULTS))


def load() -> Dict[str, Any]:
    """Returns the current config, merged with defaults for any missing key."""
    with _LOCK:
        _ensure_file()
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {**DEFAULTS, **data}


def save(config: Dict[str, Any]) -> None:
    """Overwrites the config file. Callers should merge via update() unless
    they really mean to replace everything."""
    with _LOCK:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp_path = CONFIG_PATH + ".tmp"
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with open(fd, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        os.replace(tmp_path, CONFIG_PATH)


def update(partial: Dict[str, Any]) -> Dict[str, Any]:
    """Merges partial into the stored config and saves it.

    For keys in SECRET_KEYS, an empty/None value means "leave the stored
    secret unchanged" (this is what lets the config form leave password
    fields blank on save instead of forcing a re-entry every time).
    """
    with _LOCK:
        current = load()
        for key, value in partial.items():
            if key in SECRET_KEYS and not value:
                continue
            current[key] = value
        save(current)
        return current
