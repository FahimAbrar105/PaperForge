from __future__ import annotations

from fastapi import APIRouter, Depends

from app.routes.deps import Services, services

router = APIRouter(prefix="/api/venues", tags=["venues"])


@router.get("")
def list_venues(svc: Services = Depends(services)) -> list[dict]:
    return [v.model_dump() for v in svc.registry.list()]
