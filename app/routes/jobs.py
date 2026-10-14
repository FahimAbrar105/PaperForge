"""Job API: upload, list, status, live events (SSE), cancel, downloads, delete."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse

from app.agents.report_generator import to_html
from app.agents.upload_handler import IncomingFile, UploadError, new_job_id, store_uploads
from app.models.job import JobStatus, UploadJob
from app.models.report import ComplianceReport
from app.routes.deps import Services, services
from app.services.settings_store import AGENTIC_LEVELS
from app.services.workspace import JobWorkspace, UnsafePathError

router = APIRouter(prefix="/api/jobs", tags=["jobs"])
TERMINAL = {JobStatus.completed, JobStatus.failed, JobStatus.cancelled}


def _job_or_404(svc: Services, job_id: str) -> UploadJob:
    try:
        JobWorkspace(svc.settings.jobs_dir, job_id)  # validates the id format
    except UnsafePathError:
        raise HTTPException(404, "Job not found")
    job = svc.store.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job


def _job_payload(svc: Services, job: UploadJob) -> dict:
    out = svc.store.get_outputs(job.job_id)
    data = json.loads(job.model_dump_json())
    data["downloads"] = {
        "pdf": bool(out and out.pdf_path and Path(out.pdf_path).exists()),
        "zip": bool(out and out.zip_path and Path(out.zip_path).exists()),
        "report": bool(out and out.report_html_path and Path(out.report_html_path).exists()),
    }
    return data


@router.post("")
async def create_job(venue_id: str = Form(...), files: list[UploadFile] = File(...),
                     agentic_level: str | None = Form(None), camera_ready: bool = Form(False),
                     svc: Services = Depends(services)) -> dict:
    if not svc.registry.exists(venue_id):
        raise HTTPException(400, f"Unknown or unavailable venue: {venue_id}")
    user = svc.settings_store.load()
    level = agentic_level or user.agentic_level
    if level not in AGENTIC_LEVELS:
        raise HTTPException(400, "agentic_level must be off, partial or full")
    if level != "off" and not user.ai_ready:
        raise HTTPException(400, "Agentic mode needs an AI provider. Add a free Gemini API key in Settings, "
                                 "or choose Off.")
    job_id = new_job_id()
    ws = JobWorkspace(svc.settings.jobs_dir, job_id)
    incoming = [IncomingFile(filename=f.filename or "upload", content_type=f.content_type or "", stream=f.file)
                for f in files]
    try:
        stored = await asyncio.to_thread(store_uploads, ws, incoming, svc.settings)
    except UploadError as exc:
        ws.delete()
        raise HTTPException(400, str(exc))
    finally:
        for f in files:
            await f.close()
    job = UploadJob(job_id=job_id, venue_id=venue_id, files=stored, agentic_level=level, camera_ready=camera_ready)
    svc.store.create(job)
    svc.store.add_event(job_id, "Upload Handler",
                        f"Received {len(stored)} file(s): " + ", ".join(f"{f.original_name} ({f.kind})" for f in stored),
                        "success")
    svc.runner.submit(job_id, venue_id)
    return {"job_id": job_id}


@router.get("")
def list_jobs(svc: Services = Depends(services)) -> list[dict]:
    return [_job_payload(svc, j) for j in svc.store.list(200)]


@router.get("/{job_id}")
def get_job(job_id: str, svc: Services = Depends(services)) -> dict:
    job = _job_or_404(svc, job_id)
    payload = _job_payload(svc, job)
    payload["events"] = [json.loads(e.model_dump_json()) for e in svc.store.events(job_id)]
    return payload


@router.get("/{job_id}/events")
async def job_events(job_id: str, request: Request, after: int = 0, svc: Services = Depends(services)):
    _job_or_404(svc, job_id)

    async def stream():
        last = after
        idle = 0
        while True:
            if await request.is_disconnected():
                break
            events = svc.store.events(job_id, last)
            for e in events:
                last = e.seq
                yield f"id: {e.seq}\nevent: log\ndata: {e.model_dump_json()}\n\n"
            job = svc.store.get(job_id)
            if job is None:
                break
            yield f"event: status\ndata: {json.dumps(_job_payload(svc, job), default=str)}\n\n"
            if job.status in TERMINAL and not events:
                yield "event: done\ndata: {}\n\n"
                break
            idle = idle + 1 if not events else 0
            await asyncio.sleep(0.5 if idle < 20 else 1.5)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str, svc: Services = Depends(services)) -> dict:
    job = _job_or_404(svc, job_id)
    if job.status in TERMINAL:
        return {"cancelled": False, "status": job.status.value}
    requested = svc.runner.cancel(job_id)
    if not requested:
        svc.store.update(job_id, status=JobStatus.cancelled, current_step="Cancelled")
    svc.store.add_event(job_id, "Orchestrator", "Cancellation requested by user.", "warning")
    return {"cancelled": True}


@router.get("/{job_id}/download/{kind}")
def download(job_id: str, kind: str, svc: Services = Depends(services)):
    job = _job_or_404(svc, job_id)
    out = svc.store.get_outputs(job_id)
    if out is None:
        raise HTTPException(404, "No outputs yet")
    stem = "paper"
    if job.title:
        stem = "".join(c if c.isalnum() else "_" for c in job.title)[:50].strip("_") or "paper"
    mapping = {
        "pdf": (out.pdf_path, "application/pdf", f"{stem}.pdf"),
        "zip": (out.zip_path, "application/zip", f"{stem}_latex.zip"),
        "report": (out.report_html_path, "text/html", "compliance_report.html"),
        "report-json": (out.report_json_path, "application/json", "compliance_report.json"),
        "report-md": (out.report_md_path, "text/markdown", "compliance_report.md"),
    }
    if kind not in mapping:
        raise HTTPException(404, "Unknown download")
    path, media, name = mapping[kind]
    if not path:
        raise HTTPException(404, "This output was not produced")
    p = Path(path).resolve()
    root = JobWorkspace(svc.settings.jobs_dir, job_id).root.resolve()
    if root not in p.parents or not p.is_file():
        raise HTTPException(404, "File not found")
    if kind == "report":
        return HTMLResponse(_report_page(p))
    return FileResponse(p, media_type=media, filename=name)


def _report_page(html_path: Path) -> str:
    """Rebuilt from the saved JSON so older jobs' reports get today's look and theme; the saved page if that fails."""
    try:
        return to_html(ComplianceReport.model_validate_json(html_path.with_suffix(".json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return html_path.read_text(encoding="utf-8")


@router.delete("/{job_id}")
def delete_job(job_id: str, svc: Services = Depends(services)) -> dict:
    job = _job_or_404(svc, job_id)
    if job.status not in TERMINAL:
        raise HTTPException(409, "Cancel the job before deleting it")
    JobWorkspace(svc.settings.jobs_dir, job_id).delete()
    svc.store.delete(job_id)
    return {"deleted": True}
