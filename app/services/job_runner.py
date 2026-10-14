"""Runs orchestrators in a small thread pool and tracks cancellation tokens."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from app.agents.base import StepContext
from app.agents.orchestrator import Orchestrator
from app.config import Settings
from app.models.job import JobStatus
from app.services.job_store import JobStore
from app.services.settings_store import SettingsStore
from app.services.venue_registry import VenueRegistry
from app.services.workspace import JobWorkspace


class JobRunner:
    def __init__(self, settings: Settings, store: JobStore, registry: VenueRegistry, settings_store: SettingsStore) -> None:
        self.settings = settings
        self.store = store
        self.registry = registry
        self.settings_store = settings_store
        self.pool = ThreadPoolExecutor(max_workers=max(1, settings.worker_threads), thread_name_prefix="job")
        self._cancel: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def submit(self, job_id: str, venue_id: str) -> None:
        event = threading.Event()
        with self._lock:
            self._cancel[job_id] = event
        self.pool.submit(self._run, job_id, venue_id, event)

    def _run(self, job_id: str, venue_id: str, event: threading.Event) -> None:
        try:
            if event.is_set():
                self.store.update(job_id, status=JobStatus.cancelled, current_step="Cancelled")
                self.store.add_event(job_id, "Orchestrator", "Job cancelled before it started.", "warning")
                return
            ws = JobWorkspace(self.settings.jobs_dir, job_id).create()
            ctx = StepContext(
                job_id=job_id, venue_id=venue_id, workspace=ws, settings=self.settings,
                emit=lambda step, msg, level: self.store.add_event(job_id, step, msg, level),
                cancel_event=event,
            )
            Orchestrator(ctx, self.store, self.registry, self.settings_store.load()).run()
        finally:
            with self._lock:
                self._cancel.pop(job_id, None)

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            event = self._cancel.get(job_id)
        if event is None:
            return False
        event.set()
        return True

    def shutdown(self) -> None:
        with self._lock:
            for ev in self._cancel.values():
                ev.set()
        self.pool.shutdown(wait=False, cancel_futures=True)
