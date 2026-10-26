"""Traffic simulation (NO real sensors are used). One implementation, used by the web app,
the standalone `simulate.py` script and the model-training data generator.

Model: each road has a demand level in [0.05, 1] that drifts as a mean-reverting random walk.
    cars  = level * road capacity (+- 5%)
    speed = free_flow * (1 - 0.9 * level) + noise      (speed falls as the road fills up)
"""
import logging
import os
import random
import threading

from .traffic_rules import classify

log = logging.getLogger(__name__)

# name: (free-flow speed km/h, max vehicles per interval)
ROAD_PROFILES = {
    "Main Street": (55, 120),
    "MG Road": (50, 110),
    "Airport Road": (70, 90),
    "Park Avenue": (40, 80),
}


def reading_from_level(road, level, rng):
    free_flow, capacity = ROAD_PROFILES[road]
    cars = max(0, round(level * capacity * rng.uniform(0.95, 1.05)))
    speed = free_flow * (1 - 0.9 * level) + rng.gauss(0, 2.5)
    speed = round(min(max(speed, 3.0), float(free_flow)), 1)
    return cars, speed


class TrafficSimulator:
    """Holds the per-road state and produces one reading per road each `step()`."""

    def __init__(self, seed=None):
        self.rng = random.Random(seed)
        self.levels = {r: self.rng.uniform(0.2, 0.7) for r in ROAD_PROFILES}

    def step(self):
        readings = []
        for road in ROAD_PROFILES:
            lvl = self.levels[road]
            lvl += 0.12 * (0.42 - lvl) + self.rng.gauss(0, 0.10)       # drift towards 0.42
            if self.rng.random() < 0.04:                              # occasional surge/incident
                lvl += 0.3
            self.levels[road] = lvl = min(max(lvl, 0.05), 1.0)
            cars, speed = reading_from_level(road, lvl, self.rng)
            readings.append({"road": road, "cars": cars, "speed": speed})
        return readings


def synthetic_training_data(n, seed):
    """Reproducible labelled data for model training: (X rows [cars, speed], labels).

    Half the samples come from the simulator's own distribution and half are spread uniformly
    over the whole valid input box so the model also sees unusual combinations. Labels come from
    `traffic_rules.classify`. This data is synthetic and is never stored as traffic records.
    """
    rng = random.Random(seed)
    roads = list(ROAD_PROFILES)
    X, y = [], []
    for i in range(n):
        if i % 2 == 0:
            cars, speed = reading_from_level(rng.choice(roads), rng.uniform(0.05, 1.0), rng)
        else:
            cars, speed = rng.randint(0, 150), round(rng.uniform(0, 80), 1)
        X.append([cars, speed])
        y.append(classify(cars, speed))
    return X, y


# ---- single-writer guard -------------------------------------------------------------------
class SimulatorLock:
    """OS-level file lock: only ONE process on this machine may run the simulator.
    Released automatically if the process dies. Prevents duplicate writers (e.g. several
    gunicorn workers, or the web app plus `simulate.py`)."""

    def __init__(self, path):
        self.path, self._fh = str(path), None

    def acquire(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        fh = open(self.path, "a+")
        try:
            if os.name == "nt":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            return False
        self._fh = fh
        return True

    def release(self):
        if self._fh:
            try:
                if os.name == "nt":
                    import msvcrt
                    self._fh.seek(0)
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._fh, fcntl.LOCK_UN)
            finally:
                self._fh.close()
                self._fh = None


class SimulationRunner:
    """Background thread: simulate -> classify -> store. Start once per process."""

    def __init__(self, db, classifier, interval, lock_path, seed=None, max_rows=20000):
        self.db, self.classifier, self.interval = db, classifier, interval
        self.sim = TrafficSimulator(seed)
        self.lock = SimulatorLock(lock_path)
        self.max_rows = max_rows
        self._stop = threading.Event()
        self._thread = None
        self.error = None

    @property
    def running(self):
        return bool(self._thread and self._thread.is_alive())

    def tick(self):
        for r in self.sim.step():
            status, by = self.classifier.predict(r["cars"], r["speed"])
            self.db.insert(r["road"], r["cars"], r["speed"], status, by)

    def start(self):
        if self.running:
            return True
        if not self.lock.acquire():
            log.warning("Another process already runs the simulator; this one will only read.")
            return False
        self._thread = threading.Thread(target=self._loop, name="traffic-simulator", daemon=True)
        self._thread.start()
        return True

    def _loop(self):
        ticks = 0
        while not self._stop.is_set():
            try:
                self.tick()
                ticks += 1
                if ticks % 50 == 0:
                    self.db.prune(self.max_rows)
                self.error = None
            except Exception as exc:   # logged AND exposed through /api/health, never hidden
                self.error = str(exc)
                log.exception("Simulation tick failed")
            self._stop.wait(self.interval)

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        self.lock.release()
