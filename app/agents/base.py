"""Shared context passed by the orchestrator to every pipeline step."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from app.config import Settings
from app.services.workspace import JobWorkspace

if TYPE_CHECKING:
    from app.services.ai.router import AIRouter


class JobCancelled(Exception):
    """Raised when the user cancels a job; the orchestrator turns it into status=cancelled."""


class StepError(Exception):
    """A step failed in a way the user should read about (shown verbatim in the UI)."""


@dataclass
class StepContext:
    job_id: str
    venue_id: str
    workspace: JobWorkspace
    settings: Settings
    emit: Callable[[str, str, str], None]  # (step, message, level)
    cancel_event: threading.Event = field(default_factory=threading.Event)
    ai: "AIRouter | None" = None
    data: dict[str, Any] = field(default_factory=dict)

    def log(self, step: str, message: str, level: str = "info") -> None:
        self.emit(step, message, level)

    def check_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise JobCancelled()
