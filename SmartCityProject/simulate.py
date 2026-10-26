"""Standalone simulator (alternative to the one built into the web app):  python simulate.py
Writes to the same database. Refuses to start if another simulator is already running."""
import logging
import sys
import time

from smartcity.config import Config
from smartcity.db import Database
from smartcity.ml import Classifier
from smartcity.simulator import SimulationRunner

if __name__ == "__main__":
    logging.basicConfig(level=Config.LOG_LEVEL)
    db = Database(Config.DB_PATH, Config.SQLITE_JOURNAL_MODE)
    db.init()
    runner = SimulationRunner(db, Classifier(Config.MODEL_PATH, Config.METRICS_PATH).load(),
                              Config.SIM_INTERVAL_SECONDS, Config.LOCK_PATH, Config.SIM_SEED,
                              Config.RETENTION_MAX_ROWS)
    if not runner.start():
        sys.exit("A simulator is already running (e.g. the web app). Stop it or set SIMULATOR_ENABLED=0.")
    print("Simulator running - Ctrl+C to stop")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        runner.stop()
