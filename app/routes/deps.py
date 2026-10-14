"""Shared application services, created once at startup and attached to app.state."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from app.config import Settings
from app.services.job_runner import JobRunner
from app.services.job_store import JobStore
from app.services.settings_store import SettingsStore
from app.services.venue_registry import VenueRegistry


@dataclass
class Services:
    settings: Settings
    store: JobStore
    registry: VenueRegistry
    settings_store: SettingsStore
    runner: JobRunner


def services(request: Request) -> Services:
    return request.app.state.services
