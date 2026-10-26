"""Smart City Traffic Management System (simulated data, educational project)."""
import logging

from flask import Flask

from .config import Config
from .db import Database
from .ml import Classifier
from .simulator import SimulationRunner


def create_app(config=None):
    cfg = config or Config
    logging.basicConfig(level=cfg.LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config.from_object(cfg)

    db = Database(cfg.DB_PATH, cfg.SQLITE_JOURNAL_MODE)
    db.init()
    classifier = Classifier(cfg.MODEL_PATH, cfg.METRICS_PATH).load()
    runner = SimulationRunner(db, classifier, cfg.SIM_INTERVAL_SECONDS, cfg.LOCK_PATH,
                              cfg.SIM_SEED, cfg.RETENTION_MAX_ROWS)
    app.extensions["smartcity"] = {"db": db, "classifier": classifier, "runner": runner}

    from .routes import bp
    app.register_blueprint(bp)

    if cfg.SIMULATOR_ENABLED:
        runner.start()
    return app
