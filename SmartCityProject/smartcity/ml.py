"""Congestion classifier: training, evaluation, saving, loading, prediction.

Model     : DecisionTreeClassifier (max_depth=6) - small, fast, and explainable in a viva.
Features  : [cars (vehicles per interval), speed (average km/h)]
Classes   : LOW, MEDIUM, HIGH  (see traffic_rules.py)
Training  : synthetic data labelled by the documented rules (simulator.synthetic_training_data).

HONESTY NOTE: because the labels come from deterministic rules, the held-out score measures how
well the tree has learned those rules. It is NOT evidence of real-world predictive accuracy.
"""
import json
import logging
from datetime import datetime, timezone

import joblib
import numpy as np
import sklearn
from sklearn.metrics import accuracy_score, confusion_matrix, precision_recall_fscore_support
from sklearn.model_selection import cross_val_score, train_test_split
from sklearn.tree import DecisionTreeClassifier

from .simulator import synthetic_training_data
from .traffic_rules import STATUSES, classify

log = logging.getLogger(__name__)
FEATURES = ["cars", "speed"]


def train(model_path, metrics_path, n_samples=6000, seed=42):
    """Train, evaluate on a held-out 25% split, save model + metrics. Returns the metrics dict."""
    X, y = synthetic_training_data(n_samples, seed)
    X, y = np.array(X, dtype=float), np.array(y)
    if len(X) == 0 or np.isnan(X).any():
        raise ValueError("Training data is empty or contains missing values")
    if set(y) - set(STATUSES) or len(set(y)) < len(STATUSES):
        raise ValueError(f"Training labels must cover exactly {STATUSES}, got {sorted(set(y))}")

    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.25, random_state=seed, stratify=y)
    model = DecisionTreeClassifier(max_depth=6, random_state=seed)
    model.fit(X_tr, y_tr)
    pred = model.predict(X_te)
    p, r, f1, support = precision_recall_fscore_support(y_te, pred, labels=list(STATUSES), zero_division=0)
    cv = cross_val_score(DecisionTreeClassifier(max_depth=6, random_state=seed), X, y, cv=5)

    metrics = {
        "trained_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "algorithm": "DecisionTreeClassifier(max_depth=6)",
        "features": FEATURES, "classes": list(STATUSES),
        "training_data": f"{n_samples} synthetic samples (seed={seed}), labelled by rule-based thresholds",
        "train_samples": int(len(X_tr)), "test_samples": int(len(X_te)),
        "test_accuracy": round(float(accuracy_score(y_te, pred)), 4),
        "cv5_accuracy_mean": round(float(cv.mean()), 4),
        "per_class": {c: {"precision": round(float(p[i]), 4), "recall": round(float(r[i]), 4),
                          "f1": round(float(f1[i]), 4), "support": int(support[i])}
                      for i, c in enumerate(STATUSES)},
        "confusion_matrix": {"labels": list(STATUSES),
                             "rows_are_true_columns_are_predicted":
                                 confusion_matrix(y_te, pred, labels=list(STATUSES)).tolist()},
        "sklearn_version": sklearn.__version__,
        "limitations": "Labels are produced by deterministic rules, so these scores show how well the "
                       "tree learned the rules, not real-world prediction accuracy. Inputs are simulated.",
    }
    bundle = {"model": model, "features": FEATURES, "classes": list(STATUSES),
              "sklearn_version": sklearn.__version__}
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, model_path)
    metrics_path.write_text(json.dumps(metrics, indent=2))
    log.info("Model trained: test accuracy %.4f", metrics["test_accuracy"])
    return metrics


class Classifier:
    """Loads the saved model (training it on first run). Falls back to the rules - and says so -
    if the model cannot be loaded, so the dashboard never claims ML when it is not used."""

    def __init__(self, model_path, metrics_path):
        self.model_path, self.metrics_path = model_path, metrics_path
        self.model, self.error, self.metrics = None, None, None

    def load(self, train_if_missing=True):
        try:
            self.model = self._read()
        except FileNotFoundError:
            self.error = "model file not found"
        except Exception as exc:
            self.error = f"model could not be loaded ({exc})"
        if self.model is None and train_if_missing:
            log.warning("Training a new model: %s", self.error)
            try:
                train(self.model_path, self.metrics_path)
                self.model, self.error = self._read(), None
            except Exception as exc:
                self.error = f"training failed ({exc})"
                log.exception("Model training failed; using rule-based fallback")
        self._read_metrics()
        return self

    def _read(self):
        bundle = joblib.load(self.model_path)
        if not isinstance(bundle, dict) or bundle.get("features") != FEATURES:
            raise ValueError("unexpected model format or features")
        if bundle.get("sklearn_version") != sklearn.__version__:
            raise ValueError(f"trained with scikit-learn {bundle.get('sklearn_version')}, "
                             f"installed {sklearn.__version__}")
        return bundle["model"]

    def _read_metrics(self):
        try:
            self.metrics = json.loads(self.metrics_path.read_text())
        except (OSError, ValueError):
            self.metrics = None

    @property
    def source(self):
        return "ml_model" if self.model is not None else "rules"

    def predict(self, cars, speed):
        """Return (status, source)."""
        if self.model is not None:
            return str(self.model.predict(np.array([[cars, speed]], dtype=float))[0]), "ml_model"
        return classify(cars, speed), "rules"
