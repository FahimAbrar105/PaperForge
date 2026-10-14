"""AI provider interface. Providers power the agentic modes; the app never requires one."""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod


class AIError(Exception):
    """Base class for provider failures; the router falls back on any of these."""


class AIRateLimited(AIError):
    """HTTP 429 / RESOURCE_EXHAUSTED: quota or rate limit reached.

    ``retry_after`` is the wait the provider asked for (seconds), when it said;
    ``daily`` is True when the daily quota is used up, so waiting will not help.
    """

    def __init__(self, message: str, retry_after: float | None = None, daily: bool = False) -> None:
        super().__init__(message)
        self.retry_after = retry_after
        self.daily = daily


class AIUnavailable(AIError):
    """Provider not configured, unreachable, timed out, or rejected the request."""


class AIBadResponse(AIError):
    """Provider answered but not with valid JSON of the expected shape."""


class AIProvider(ABC):
    name: str = "provider"
    last_model: str = ""  # the model that gave the last answer

    @abstractmethod
    def available(self) -> bool:
        """Cheap check that the provider is configured (and reachable, for local servers)."""

    @abstractmethod
    def generate_json(self, system: str, prompt: str, timeout_s: int = 60) -> dict:
        """Return the model's JSON answer as a dict, or raise an AIError."""


def extract_json(text: str) -> dict:
    """Parse a JSON object from model output, tolerating code fences or surrounding prose."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise AIBadResponse("Response did not contain JSON") from None
        try:
            value = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise AIBadResponse(f"Invalid JSON from model: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise AIBadResponse("Expected a JSON object")
    return value
