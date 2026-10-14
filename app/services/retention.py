"""Delete job files older than the retention period."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services.job_store import JobStore
from app.services.workspace import JobWorkspace

log = logging.getLogger("paperforge.retention")


def sweep(store: JobStore, jobs_dir: Path, retention_days: int) -> int:
    """Remove workspaces and history rows older than ``retention_days``. 0 disables."""
    if retention_days <= 0:
        return 0
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
    removed = 0
    for job_id in store.older_than(cutoff):
        try:
            JobWorkspace(jobs_dir, job_id).delete()
        except ValueError:
            pass
        store.delete(job_id)
        removed += 1
    if removed:
        log.info("Retention sweep removed %d old job(s)", removed)
    return removed


class RetentionSweeper:
    """Runs ``sweep`` at startup and then every few hours in a daemon thread."""

    def __init__(self, store: JobStore, jobs_dir: Path, days_getter, interval_s: int = 6 * 3600) -> None:
        self.store = store
        self.jobs_dir = jobs_dir
        self.days_getter = days_getter
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="retention", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                sweep(self.store, self.jobs_dir, int(self.days_getter()))
            except Exception:  # never let the sweeper kill the app
                log.exception("Retention sweep failed")
            self._stop.wait(self.interval_s)
