"""SQLite access layer. One short-lived connection per operation, parameterised SQL only."""
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from .traffic_rules import STATUSES

log = logging.getLogger(__name__)

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS traffic_records (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    road         TEXT    NOT NULL,
    cars         INTEGER NOT NULL CHECK (cars >= 0),
    speed        REAL    NOT NULL CHECK (speed >= 0),
    status       TEXT    NOT NULL CHECK (status IN ({", ".join(repr(s) for s in STATUSES)})),
    predicted_by TEXT    NOT NULL CHECK (predicted_by IN ('ml_model', 'rules')),
    recorded_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_records_road_id ON traffic_records (road, id DESC);
"""


class Database:
    def __init__(self, path, journal_mode="WAL"):
        self.path = str(path)
        self.journal_mode = journal_mode

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init(self):
        """Create the folder, tables and indexes if missing (safe to call repeatedly)."""
        import os
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with self.connect() as conn:
            try:
                conn.execute(f"PRAGMA journal_mode={self.journal_mode}")
            except sqlite3.DatabaseError:
                log.warning("Could not set journal mode %s; using default", self.journal_mode)
            conn.executescript(SCHEMA)

    def insert(self, road, cars, speed, status, predicted_by):
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO traffic_records (road, cars, speed, status, predicted_by, recorded_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (road, cars, speed, status, predicted_by,
                 datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))

    def recent(self, limit=20):
        """Newest first, deterministic (id is strictly increasing)."""
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM traffic_records ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
        return [dict(r) for r in rows]

    def latest_per_road(self, per_road=1):
        """The newest `per_road` rows of every road."""
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id, road, cars, speed, status, predicted_by, recorded_at FROM ("
                "  SELECT *, ROW_NUMBER() OVER (PARTITION BY road ORDER BY id DESC) AS rn "
                "  FROM traffic_records) WHERE rn <= ? ORDER BY road, id DESC", (int(per_road),)).fetchall()
        return [dict(r) for r in rows]

    def count(self):
        with self.connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM traffic_records").fetchone()[0]

    def status_counts(self, last_n=200):
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM (SELECT status FROM traffic_records "
                "ORDER BY id DESC LIMIT ?) GROUP BY status", (int(last_n),)).fetchall()
        counts = {s: 0 for s in STATUSES}
        counts.update({r["status"]: r["n"] for r in rows})
        return counts

    def prune(self, max_rows):
        """Keep only the newest `max_rows` rows so the database cannot grow forever."""
        with self.connect() as conn:
            conn.execute(
                "DELETE FROM traffic_records WHERE id <= "
                "(SELECT COALESCE(MAX(id), 0) - ? FROM traffic_records)", (int(max_rows),))
