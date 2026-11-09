"""Environment loading and the list of URLs the pipeline may fetch.

ALLOWED_PREFIXES is the code-level form of the project rule "only API results and
Circular T". Anything not listed here is refused by PoliteClient before a request
is made. Adding a prefix is a deliberate, reviewable change.
"""

import os
from pathlib import Path

from timeglobe_pipeline import __version__

PROJECT_URL = "https://time.anzarahmad.me"

ALLOWED_PREFIXES: tuple[str, ...] = (
    "https://webtai.bipm.org/api/v1.0/",
    "https://webtai.bipm.org/database/",
    "https://www.bipm.org/en/time-ftp/circular-t",
    "https://www.ntppool.org/zone/",
    # Only to sanity-check hand-entered lab coordinates (1 request/s). Results are not stored
    # in the product; attribution: "Geocoding © OpenStreetMap contributors".
    "https://nominatim.openstreetmap.org/search",
    # Published Circular T issues only. Any other /ftp/ path needs maintainer approval first.
    "https://webtai.bipm.org/ftp/pub/tai/Circular-T/cirt/",
)

# Raw lab data belongs to the labs and is never fetched. Checked before the allowlist.
FORBIDDEN_PREFIXES: tuple[str, ...] = ("https://webtai.bipm.org/ftp/pub/tai/data/",)


def _parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        if value:
            values[key.strip()] = value
    return values


def load_env(path: Path) -> None:
    """Load KEY=VALUE lines into os.environ without overriding existing values."""
    for key, value in _parse_env(path).items():
        os.environ.setdefault(key, value)


def env_value(key: str, path: Path | None = None) -> str:
    """One setting from the environment, else from .env, without touching os.environ.
    For code that must read a single secret and not pull the others into the process."""
    found = os.environ.get(key, "").strip()
    if found:
        return found
    return _parse_env(path or Path(__file__).resolve().parents[3] / ".env").get(key, "")


def user_agent() -> str:
    contact = os.environ.get("TIMEGLOBE_CONTACT", "").strip()
    if not contact:
        raise RuntimeError("TIMEGLOBE_CONTACT is not set; add it to .env (see .env.example)")
    return f"TimeGlobe/{__version__} (+{PROJECT_URL}; contact: {contact})"


DB_OPT_IN = "TIMEGLOBE_ALLOW_DB"


def require_db_opt_in() -> None:
    """Refuse to touch a database unless the process was explicitly started with
    TIMEGLOBE_ALLOW_DB=1. It is read from the process environment only, never from .env, so
    a database is only reached by a run someone chose to make (the workflow sets it)."""
    if os.environ.get(DB_OPT_IN) != "1":
        raise SystemExit(f"refusing to connect to a database: set {DB_OPT_IN}=1 for this run")
