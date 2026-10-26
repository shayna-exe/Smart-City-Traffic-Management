"""Train and evaluate the congestion model:  python train_model.py"""
import json
import logging

from smartcity.config import Config
from smartcity.ml import train

if __name__ == "__main__":
    logging.basicConfig(level="INFO")
    m = train(Config.MODEL_PATH, Config.METRICS_PATH)
    print(json.dumps({k: m[k] for k in ("algorithm", "train_samples", "test_samples", "test_accuracy",
                                         "cv5_accuracy_mean", "per_class", "confusion_matrix")}, indent=2))
    print("\nNote:", m["limitations"])
    print("Saved:", Config.MODEL_PATH)
