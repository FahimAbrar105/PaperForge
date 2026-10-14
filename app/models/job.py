from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class UploadedFile(BaseModel):
    original_name: str
    stored_name: str
    kind: str  # manuscript | bibliography | figure | data
    extension: str
    size_bytes: int
    sha256: str


class UploadJob(BaseModel):
    job_id: str
    venue_id: str
    status: JobStatus = JobStatus.queued
    current_step: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    files: list[UploadedFile] = Field(default_factory=list)
    error: str | None = None
    overall_status: str | None = None  # copied from the compliance report
    title: str | None = None
    agentic_level: str = "off"  # requested: off | partial | full
    agentic_achieved: str | None = None  # what happened: off | partial | full
    camera_ready: bool = False  # double-blind venues: the accepted version with authors, not the anonymous one


class JobEvent(BaseModel):
    job_id: str
    seq: int = 0
    timestamp: datetime = Field(default_factory=utcnow)
    step: str
    level: str = "info"  # info | warning | error | success
    message: str


class FinalOutput(BaseModel):
    job_id: str
    pdf_path: str | None = None
    zip_path: str | None = None
    report_json_path: str | None = None
    report_html_path: str | None = None
    report_md_path: str | None = None
    overall_status: str
