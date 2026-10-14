"""HTML pages (static files; all dynamic data comes from the JSON API)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, JSONResponse

from app.routes.deps import Services, services

router = APIRouter()


@router.get("/", include_in_schema=False)
def index(svc: Services = Depends(services)):
    return FileResponse(svc.settings.static_dir / "index.html")


@router.get("/settings", include_in_schema=False)
def settings_page(svc: Services = Depends(services)):
    return FileResponse(svc.settings.static_dir / "settings.html")


@router.get("/jobs/{job_id}", include_in_schema=False)
def job_page(job_id: str, svc: Services = Depends(services)):
    return FileResponse(svc.settings.static_dir / "job.html")


@router.get("/healthz", include_in_schema=False)
def healthz(svc: Services = Depends(services)):
    return JSONResponse({"status": "ok", "tectonic": bool(svc.settings.tectonic_path)})
