"""User settings stored locally in output/settings.json.

The Gemini API key never leaves this file except in requests to the Gemini API,
and is always masked when returned to the UI or written to logs.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

# off: rules only, offline. partial: AI only for hard cases (at most 3 requests).
# full: an AI agent drives every step that can use one; steps switch to rules
# automatically when the AI limit is reached.
AgenticLevel = Literal["off", "partial", "full"]
AIProviderName = Literal["gemini", "ollama"]
AGENTIC_LEVELS = ("off", "partial", "full")

DEFAULT_GEMINI_MODEL = "gemini-flash-latest"
DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "llama3.2:3b"
DEFAULT_AGENT_CALLS = 12
MAX_AGENT_CALLS = 30

# Settings files written before agentic levels existed used a single "ai_mode".
_LEGACY_MODES = {"deterministic": ("off", None), "gemini": ("partial", "gemini"),
                 "auto": ("partial", "gemini"), "ollama": ("partial", "ollama")}


class UserSettings(BaseModel):
    agentic_level: AgenticLevel = "off"
    ai_provider: AIProviderName = "gemini"
    gemini_api_key: str = ""
    gemini_model: str = DEFAULT_GEMINI_MODEL
    ollama_enabled: bool = False  # use Ollama when Gemini is unavailable or out of quota
    ollama_base_url: str = DEFAULT_OLLAMA_URL
    ollama_model: str = DEFAULT_OLLAMA_MODEL
    max_agent_calls: int = Field(default=DEFAULT_AGENT_CALLS, ge=1, le=MAX_AGENT_CALLS)
    retention_days: int | None = Field(default=None, ge=0, le=3650)

    @model_validator(mode="before")
    @classmethod
    def _upgrade_legacy(cls, data):
        if isinstance(data, dict) and "ai_mode" in data:
            data = dict(data)
            mode = data.pop("ai_mode")
            level, provider = _LEGACY_MODES.get(mode, ("off", None))
            data.setdefault("agentic_level", level)
            if provider:
                data.setdefault("ai_provider", provider)
            if mode == "auto":
                data.setdefault("ollama_enabled", True)
        return data

    @property
    def ai_ready(self) -> bool:
        """True when at least one AI provider is configured (Ollama is checked only when used)."""
        if self.ai_provider == "ollama":
            return True
        return bool(self.gemini_api_key) or self.ollama_enabled


class PublicSettings(BaseModel):
    agentic_level: AgenticLevel
    ai_provider: AIProviderName
    ai_ready: bool
    gemini_key_set: bool
    gemini_key_masked: str
    gemini_model: str
    ollama_enabled: bool
    ollama_base_url: str
    ollama_model: str
    max_agent_calls: int
    retention_days: int | None


def mask_secret(secret: str) -> str:
    if not secret:
        return ""
    if len(secret) <= 8:
        return "*" * len(secret)
    return f"{secret[:4]}{'*' * (len(secret) - 8)}{secret[-4:]}"


def redact(text: str, settings: UserSettings | None) -> str:
    """Remove the API key from any text before it is logged or shown."""
    if settings and settings.gemini_api_key and settings.gemini_api_key in text:
        text = text.replace(settings.gemini_api_key, mask_secret(settings.gemini_api_key))
    return text


class SettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def load(self) -> UserSettings:
        with self._lock:
            if not self.path.exists():
                settings = UserSettings()
            else:
                try:
                    settings = UserSettings.model_validate_json(self.path.read_text(encoding="utf-8"))
                except (ValueError, OSError):
                    settings = UserSettings()
        env_key = os.environ.get("PAPERFORGE_GEMINI_API_KEY")
        if env_key and not settings.gemini_api_key:
            settings.gemini_api_key = env_key
        return settings

    def save(self, settings: UserSettings) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(settings.model_dump_json(indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass

    def update(self, changes: dict) -> UserSettings:
        current = self.load()
        data = current.model_dump()
        for key, value in changes.items():
            if key not in data or value is None:
                continue
            # An empty or masked key from the UI means "keep the stored key".
            if key == "gemini_api_key" and (value == "" or "*" in str(value)):
                continue
            data[key] = value.strip() if isinstance(value, str) else value
        if changes.get("clear_gemini_key"):
            data["gemini_api_key"] = ""
        updated = UserSettings.model_validate(data)
        self.save(updated)
        return updated

    @staticmethod
    def public(settings: UserSettings) -> PublicSettings:
        return PublicSettings(
            agentic_level=settings.agentic_level,
            ai_provider=settings.ai_provider,
            ai_ready=settings.ai_ready,
            gemini_key_set=bool(settings.gemini_api_key),
            gemini_key_masked=mask_secret(settings.gemini_api_key),
            gemini_model=settings.gemini_model,
            ollama_enabled=settings.ollama_enabled,
            ollama_base_url=settings.ollama_base_url,
            ollama_model=settings.ollama_model,
            max_agent_calls=settings.max_agent_calls,
            retention_days=settings.retention_days,
        )
