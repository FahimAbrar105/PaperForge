"""SQLite persistence for jobs, job events and outputs."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    venue_id TEXT NOT NULL,
    status TEXT NOT NULL,
    current_step TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    files_json TEXT NOT NULL DEFAULT '[]',
    error TEXT,
    overall_status TEXT,
    title TEXT,
    outputs_json TEXT,
    agentic_level TEXT NOT NULL DEFAULT 'off',
    agentic_achieved TEXT,
    camera_ready INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS job_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    step TEXT NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_job ON job_events(job_id, id);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        """Add columns introduced after the first release to existing databases."""
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(jobs)").fetchall()}
        if "agentic_level" not in cols:
            self._conn.execute("ALTER TABLE jobs ADD COLUMN agentic_level TEXT NOT NULL DEFAULT 'off'")
        if "agentic_achieved" not in cols:
            self._conn.execute("ALTER TABLE jobs ADD COLUMN agentic_achieved TEXT")
        if "camera_ready" not in cols:
            self._conn.execute("ALTER TABLE jobs ADD COLUMN camera_ready INTEGER NOT NULL DEFAULT 0")

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, params).fetchall())

    def close(self) -> None:
        with self._lock:
            self._conn.close()
