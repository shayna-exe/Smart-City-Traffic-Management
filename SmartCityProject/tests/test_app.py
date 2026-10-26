"""Run with:  python -m unittest discover -s tests -v   (standard library only)"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from smartcity import analysis, create_app                                  # noqa: E402
from smartcity.config import Config                                          # noqa: E402
from smartcity.ml import Classifier, train                                   # noqa: E402
from smartcity.simulator import SimulatorLock, TrafficSimulator, synthetic_training_data  # noqa: E402
from smartcity.traffic_rules import (HIGH, LOW, MEDIUM, STATUSES, classify,  # noqa: E402
                                     normalize_status, validate_reading)


def make_config(folder, **over):
    folder = Path(folder)
    attrs = dict(DATA_DIR=folder, DB_PATH=folder / "t.db", MODEL_PATH=folder / "m.joblib",
                 METRICS_PATH=folder / "m.metrics.json", SIMULATOR_ENABLED=False,
                 LOCK_PATH=folder / "sim.lock", SIM_SEED=7, SQLITE_JOURNAL_MODE="DELETE")
    attrs.update(over)
    return type("TestConfig", (Config,), attrs)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)


class AppCase(Base):
    def setUp(self):
        super().setUp()
        self.cfg = make_config(self.tmp)
        self.app = create_app(self.cfg)
        self.addCleanup(self.app.extensions["smartcity"]["runner"].stop)
        self.client = self.app.test_client()
        self.ext = self.app.extensions["smartcity"]


class TestRules(unittest.TestCase):
    def test_classify(self):
        for cars, speed, exp in [(100, 10, HIGH), (60, 19.9, HIGH), (59, 10, MEDIUM), (80, 50, MEDIUM),
                                 (30, 34, MEDIUM), (30, 50, LOW), (0, 0, MEDIUM)]:
            with self.subTest(cars=cars, speed=speed):
                self.assertEqual(classify(cars, speed), exp)

    def test_normalize_status(self):
        self.assertEqual(normalize_status("HIGH CONGESTION"), HIGH)
        self.assertEqual(normalize_status(" high "), HIGH)
        self.assertEqual(normalize_status("Medium"), MEDIUM)
        self.assertEqual(normalize_status("low"), LOW)
        with self.assertRaises(ValueError):
            normalize_status("bogus")

    def test_validate_reading_rejects_bad_input(self):
        for cars, speed in [("x", 1), (1, None), (-1, 10), (10, -5), (1000, 10), (10, 999),
                            (float("nan"), 1), (1, float("inf"))]:
            with self.subTest(cars=cars, speed=speed), self.assertRaises(ValueError):
                validate_reading(cars, speed)
        self.assertEqual(validate_reading("12", "33.33"), (12, 33.3))


class TestAnalysis(unittest.TestCase):
    def test_carbon_and_air_quality(self):
        self.assertEqual(analysis.get_carbon_kg(0, 50), 0)
        self.assertAlmostEqual(analysis.get_carbon_kg(100, 60), 13.0, places=2)   # 100 * (90 + 40) g
        self.assertGreater(analysis.get_carbon_kg(50, 10), analysis.get_carbon_kg(50, 60))
        self.assertGreater(analysis.get_carbon_kg(10, 0), 0)                       # no divide-by-zero
        self.assertEqual([analysis.get_air_quality(v) for v in (2, 10, 30)], ["Good", "Moderate", "Poor"])

    def test_emergency_corridor(self):
        data = [{"road": "A", "cars": 90, "speed": 12, "status": HIGH},
                {"road": "B", "cars": 40, "speed": 30, "status": MEDIUM},
                {"road": "C", "cars": 20, "speed": 50, "status": LOW}]
        self.assertEqual(analysis.emergency_corridor(data)["recommended"]["road"], "C")
        self.assertIsNone(analysis.emergency_corridor([]))
        self.assertIsNone(analysis.emergency_corridor([{"road": "X"}]))             # incomplete row skipped
        mixed = [{"road": "H", "cars": 70, "speed": 19, "status": HIGH},
                 {"road": "M", "cars": 10, "speed": 15, "status": MEDIUM}]
        self.assertEqual(analysis.emergency_corridor(mixed)["recommended"]["road"], "M")


class TestML(Base):
    def test_training_and_evaluation(self):
        m = train(self.tmp / "m.joblib", self.tmp / "m.json", n_samples=2000)
        self.assertEqual((m["train_samples"], m["test_samples"]), (1500, 500))     # held-out split
        self.assertGreater(m["test_accuracy"], 0.95)
        self.assertEqual(set(m["per_class"]), set(STATUSES))
        self.assertTrue((self.tmp / "m.joblib").exists())

    def test_training_data_standard_and_reproducible(self):
        a, b = synthetic_training_data(300, 1), synthetic_training_data(300, 1)
        self.assertEqual(a, b)
        self.assertLessEqual(set(a[1]), set(STATUSES))

    def test_predictions_match_rules(self):
        c = Classifier(self.tmp / "m.joblib", self.tmp / "m.json").load()
        self.assertEqual(c.source, "ml_model")
        for cars, speed in [(100, 8), (20, 60), (45, 25), (75, 18), (65, 40)]:
            self.assertEqual(c.predict(cars, speed), (classify(cars, speed), "ml_model"))

    def test_corrupt_model_is_retrained(self):
        (self.tmp / "m.joblib").write_text("garbage")
        self.assertEqual(Classifier(self.tmp / "m.joblib", self.tmp / "m.json").load().source, "ml_model")

    def test_rule_fallback_is_labelled(self):
        (self.tmp / "m.joblib").write_text("garbage")
        c = Classifier(self.tmp / "m.joblib", self.tmp / "m.json").load(train_if_missing=False)
        self.assertEqual(c.predict(100, 5), (HIGH, "rules"))
        self.assertTrue(c.error)


class TestStartup(Base):
    def test_first_start_creates_db_and_model(self):
        cfg = make_config(self.tmp / "fresh" / "nested")
        app = create_app(cfg)
        self.assertTrue(cfg.DB_PATH.exists() and cfg.MODEL_PATH.exists())
        self.assertEqual(app.test_client().get("/api/health").get_json()["classifier"], "ml_model")

    def test_start_with_existing_db_and_model(self):
        cfg = make_config(self.tmp)
        create_app(cfg).extensions["smartcity"]["db"].insert("Main Street", 10, 50, LOW, "ml_model")
        again = create_app(cfg)
        self.assertEqual(again.test_client().get("/api/health").get_json()["records"], 1)


class TestApi(AppCase):
    def test_dashboard_renders_with_no_records(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Smart City Traffic", r.data)
        self.assertFalse(self.client.get("/api/summary").get_json()["has_data"])
        self.assertEqual(self.client.get("/api/records").get_json()["records"], [])
        t = self.client.get("/api/trends").get_json()
        self.assertEqual((t["points"], t["status_counts"]), ([], {"LOW": 0, "MEDIUM": 0, "HIGH": 0}))

    def test_simulation_inserts_and_summary_is_correct(self):
        for _ in range(3):
            self.ext["runner"].tick()
        self.assertEqual(self.ext["db"].count(), 12)                                # 4 roads x 3 ticks
        s = self.client.get("/api/summary").get_json()
        latest = self.ext["db"].latest_per_road(1)
        self.assertTrue(s["has_data"])
        self.assertEqual(s["monitored_roads"], 4)
        self.assertEqual(s["total_vehicles"], sum(r["cars"] for r in latest))
        self.assertAlmostEqual(s["average_speed"], sum(r["speed"] for r in latest) / 4, delta=0.1)
        self.assertEqual(s["congested_roads"], sum(r["status"] == HIGH for r in latest))
        self.assertIn(s["emergency"]["recommended"]["road"], {r["road"] for r in latest})
        recs = self.client.get("/api/records?limit=5").get_json()["records"]
        self.assertEqual(len(recs), 5)
        self.assertGreater(recs[0]["id"], recs[1]["id"])                            # newest first
        self.assertTrue(all(r["predicted_by"] == "ml_model" and r["status"] in STATUSES for r in recs))

    def test_stored_status_matches_rules(self):
        self.ext["runner"].tick()
        for r in self.ext["db"].recent(10):
            self.assertEqual(r["status"], classify(r["cars"], r["speed"]))

    def test_predict_endpoint(self):
        j = self.client.get("/api/predict?cars=90&speed=10").get_json()
        self.assertEqual((j["status"], j["rule_status"]), (HIGH, HIGH))

    def test_predict_invalid_input(self):
        for q in ["", "?cars=abc&speed=3", "?cars=10", "?cars=-5&speed=10", "?cars=10&speed=9999", "?cars=nan&speed=5"]:
            with self.subTest(q=q):
                r = self.client.get("/api/predict" + q)
                self.assertEqual(r.status_code, 400)
                self.assertIn("error", r.get_json())

    def test_records_invalid_limit(self):
        for q in ["?limit=0", "?limit=500", "?limit=abc"]:
            with self.subTest(q=q):
                self.assertEqual(self.client.get("/api/records" + q).status_code, 400)

    def test_errors_do_not_leak_internals(self):
        self.assertEqual(self.client.get("/api/nope").status_code, 404)
        r = self.client.get("/nope")
        self.assertEqual(r.status_code, 404)
        self.assertNotIn(b"Traceback", r.data)

    def test_model_and_health(self):
        m = self.client.get("/api/model").get_json()
        self.assertEqual(m["active"], "ml_model")
        self.assertGreater(m["metrics"]["test_accuracy"], 0.9)
        h = self.client.get("/api/health").get_json()
        self.assertEqual((h["status"], h["data_source"]), ("ok", "simulated"))

    def test_prune_keeps_newest(self):
        for _ in range(5):
            self.ext["runner"].tick()
        self.ext["db"].prune(8)
        self.assertEqual(self.ext["db"].count(), 8)


class TestSimulator(Base):
    def test_only_one_simulator_lock(self):
        a, b = SimulatorLock(self.tmp / "l"), SimulatorLock(self.tmp / "l")
        self.assertTrue(a.acquire())
        self.assertFalse(b.acquire())
        a.release()
        self.assertTrue(b.acquire())
        b.release()

    def test_background_thread_writes(self):
        app = create_app(make_config(self.tmp, SIMULATOR_ENABLED=True, SIM_INTERVAL_SECONDS=0.1))
        runner = app.extensions["smartcity"]["runner"]
        time.sleep(0.7)
        self.assertTrue(runner.running)
        self.assertGreaterEqual(app.extensions["smartcity"]["db"].count(), 4)
        runner.stop()
        self.assertFalse(runner.running)

    def test_seed_reproducible(self):
        self.assertEqual(TrafficSimulator(5).step(), TrafficSimulator(5).step())


class TestProductionStartup(Base):
    def _free_port(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def test_wsgi_entrypoint_serves_and_simulates(self):
        """Imports the real `app:app` object exactly like a WSGI server does and serves it."""
        env = {"SMARTCITY_DATA_DIR": str(self.tmp), "SMARTCITY_LOCK_PATH": str(self.tmp / "l.lock"),
               "SIM_INTERVAL_SECONDS": "0.2"}
        out = subprocess.run([sys.executable, str(ROOT / "tests" / "_wsgi_probe.py")], env={**os.environ, **env},
                             capture_output=True, text=True, timeout=60, cwd=self.tmp)
        self.assertEqual(out.returncode, 0, out.stderr[-500:])
        result = json.loads(out.stdout.strip().splitlines()[-1])
        self.assertEqual(result["page_status"], 200)
        h = result["health"]
        self.assertTrue(h["simulator_running_here"])
        self.assertGreater(h["records"], 0)

    @unittest.skipUnless(shutil.which("gunicorn") and sys.platform != "win32", "gunicorn not installed")
    def test_gunicorn_serves_app(self):
        port = self._free_port()
        env = {**os.environ, "SMARTCITY_DATA_DIR": str(self.tmp), "SMARTCITY_LOCK_PATH": str(self.tmp / "l.lock"),
               "SIM_INTERVAL_SECONDS": "0.2"}
        p = subprocess.Popen(["gunicorn", "--bind", f"127.0.0.1:{port}", "--workers", "1", "--threads", "2", "app:app"],
                             cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(60):
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1)
                    break
                except OSError:
                    time.sleep(0.5)
            else:
                self.fail("gunicorn did not start")
            time.sleep(1.5)
            h = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health").read())
            self.assertTrue(h["simulator_running_here"] and h["records"] > 0)
        finally:
            p.terminate()
            p.wait(10)


if __name__ == "__main__":
    unittest.main()
