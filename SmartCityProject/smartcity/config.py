"""Central configuration. Every setting can be overridden with an environment variable,
so the same code runs locally and on Azure without edits."""
import os
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _bool(name, default):
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _num(name, default, cast=int):
    raw = os.environ.get(name)
    if raw in (None, ""):
        return default
    try:
        return cast(raw)
    except ValueError:
        raise ValueError(f"Environment variable {name}={raw!r} must be a {cast.__name__}")


class Config:
    DATA_DIR = Path(os.environ.get("SMARTCITY_DATA_DIR", BASE_DIR / "data"))
    DB_PATH = Path(os.environ.get("SMARTCITY_DB_PATH", DATA_DIR / "traffic.db"))
    MODEL_PATH = Path(os.environ.get("SMARTCITY_MODEL_PATH", DATA_DIR / "traffic_model.joblib"))
    METRICS_PATH = MODEL_PATH.with_suffix(".metrics.json")
    # WAL is best locally. On network file systems (Azure /home) use DELETE.
    SQLITE_JOURNAL_MODE = os.environ.get("SQLITE_JOURNAL_MODE", "WAL").upper()

    SIMULATOR_ENABLED = _bool("SIMULATOR_ENABLED", True)
    SIM_INTERVAL_SECONDS = _num("SIM_INTERVAL_SECONDS", 5.0, float)
    SIM_SEED = _num("SIM_SEED", None) if os.environ.get("SIM_SEED") else None
    RETENTION_MAX_ROWS = _num("RETENTION_MAX_ROWS", 20000)
    # The simulator lock lives on the local disk so it works even if DATA_DIR is a network share.
    LOCK_PATH = Path(os.environ.get("SMARTCITY_LOCK_PATH", Path(tempfile.gettempdir()) / "smartcity_simulator.lock"))

    HOST = os.environ.get("HOST", "127.0.0.1")
    PORT = _num("PORT", 5000)
    DEBUG = _bool("FLASK_DEBUG", False)
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
