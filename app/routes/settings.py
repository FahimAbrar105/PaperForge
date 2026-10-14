"""Settings API. The Gemini key is write-only from the browser's point of view."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.routes.deps import Services, services
from app.services.ai.base import AIError
from app.services.ai.gemini import GeminiProvider, list_models
from app.services.ai.ollama import OllamaProvider
from app.services.settings_store import MAX_AGENT_CALLS, AgenticLevel, AIProviderName, UserSettings, redact

router = APIRouter(prefix="/api/settings", tags=["settings"])
NEEDS_KEY = "Full and Partial modes with Gemini need an API key. Paste one above, or choose Off."


class SettingsUpdate(BaseModel):
    agentic_level: AgenticLevel | None = None
    ai_provider: AIProviderName | None = None
    max_agent_calls: int | None = Field(default=None, ge=1, le=MAX_AGENT_CALLS)
    gemini_api_key: str | None = Field(default=None, max_length=200)
    clear_gemini_key: bool = False
    gemini_model: str | None = Field(default=None, max_length=100, pattern=r"^[A-Za-z0-9._\-]*$")
    ollama_enabled: bool | None = None
    ollama_base_url: str | None = Field(default=None, max_length=200, pattern=r"^https?://[^\s]+$")
    ollama_model: str | None = Field(default=None, max_length=100, pattern=r"^[A-Za-z0-9._:\-/]*$")
    retention_days: int | None = Field(default=None, ge=0, le=3650)


@router.get("")
def get_settings_api(svc: Services = Depends(services)) -> dict:
    s = svc.settings_store.load()
    data = svc.settings_store.public(s).model_dump()
    data["effective_retention_days"] = s.retention_days if s.retention_days is not None else svc.settings.retention_days
    data["tectonic_found"] = bool(svc.settings.tectonic_path)
    return data


def _ai_ready_after(current: UserSettings, update: SettingsUpdate) -> bool:
    """Whether an AI provider is set up once this update is saved (a masked key keeps the stored one)."""
    new_key = (update.gemini_api_key or "").strip()
    key = "" if update.clear_gemini_key else (new_key if new_key and "*" not in new_key else current.gemini_api_key)
    provider = update.ai_provider or current.ai_provider
    ollama = current.ollama_enabled if update.ollama_enabled is None else update.ollama_enabled
    return provider == "ollama" or bool(key) or ollama


@router.put("")
def update_settings(update: SettingsUpdate, svc: Services = Depends(services)) -> dict:
    current = svc.settings_store.load()
    if (update.agentic_level or current.agentic_level) != "off" and not _ai_ready_after(current, update):
        raise HTTPException(400, NEEDS_KEY)
    changes = update.model_dump(exclude_none=True)
    updated = svc.settings_store.update(changes)
    return svc.settings_store.public(updated).model_dump()


@router.get("/gemini-models")
async def gemini_models(svc: Services = Depends(services)) -> dict:
    s = svc.settings_store.load()
    if not s.gemini_api_key:
        raise HTTPException(400, "Save a Gemini API key to see the models it can use.")
    try:
        models = await asyncio.to_thread(list_models, s.gemini_api_key)
    except AIError as exc:
        raise HTTPException(502, redact(str(exc), s)) from None
    return {"models": models}


@router.post("/test-ai")
async def test_ai(provider: str, model: str | None = Query(default=None, max_length=100, pattern=r"^[A-Za-z0-9._\-]*$"),
                  svc: Services = Depends(services)) -> dict:
    s = svc.settings_store.load()
    if provider == "gemini":
        if not s.gemini_api_key:
            raise HTTPException(400, "Save a Gemini API key first.")
        p = GeminiProvider(s.gemini_api_key, model or s.gemini_model)
    elif provider == "ollama":
        p = OllamaProvider(s.ollama_base_url, s.ollama_model)
        if not await asyncio.to_thread(p.available):
            return {"ok": False, "message": f"Ollama is not reachable at {s.ollama_base_url}."}
    else:
        raise HTTPException(400, "provider must be gemini or ollama")
    try:
        answer = await asyncio.to_thread(p.generate_json, "Reply with JSON only.", 'Return {"ok": true}.', 30)
    except AIError as exc:
        return {"ok": False, "message": redact(str(exc), s)}
    ok = bool(answer.get("ok", True))
    if provider == "gemini" and p.last_model != p.chosen:
        return {"ok": ok, "message": f"{p.chosen} could not answer right now, so Paper Forge asked "
                                     f"{p.last_model}, which answered correctly."}
    return {"ok": ok, "message": f"{provider} ({p.last_model}) answered correctly."}
