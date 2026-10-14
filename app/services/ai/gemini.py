"""Google Gemini API (free tier) over plain HTTPS. No SDK required.

The API key belongs to the end user, is read from local settings, and is sent
only in the ``x-goog-api-key`` header to Google's endpoint (never in a URL, so
it cannot leak into logs).
"""

from __future__ import annotations

import http.client
import json
import math
import os
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Callable

from app.services.ai.base import AIBadResponse, AIError, AIProvider, AIRateLimited, AIUnavailable, extract_json
from app.services.settings_store import DEFAULT_GEMINI_MODEL

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# Google retires model versions, its newest models are often too busy to answer, and the free tier allows only a
# few requests a day per model. So a request first goes to the chosen model, then the Flash models below it (newest
# first), then the model that answered last, the newer Flash models, and these names for the current Flash models.
BACKUP_MODELS = ("gemini-flash-latest", "gemini-flash-lite-latest")
FLASH_RE = re.compile(r"gemini-(\d+(?:\.\d+)?)-flash(-lite)?")
NOT_FOR_TEXT = re.compile(r"tts|image|embedding|audio|live|robotics|computer-use")
MAX_BUSY_MODELS_PER_REQUEST = 5  # retired and out-of-quota models answer at once, so they do not count
BUSY_WAIT_S = 20.0
_unusable_until: dict[str, float] = {}  # retired models for good, models out of daily quota until it resets
_flash_models: list[str] | None = None
_last_good: str | None = None

# The free tier allows only a few requests per minute. Requests from all jobs are
# spaced at least this many seconds apart so a fully agentic job stays under it.
_pace_lock = threading.Lock()
_last_request = 0.0


def _min_interval() -> float:
    try:
        return max(0.0, float(os.environ.get("PAPERFORGE_GEMINI_MIN_INTERVAL", "4")))
    except ValueError:
        return 4.0


def _pace() -> None:
    global _last_request
    with _pace_lock:
        wait = _last_request + _min_interval() - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()


def parse_rate_limit(body: dict) -> tuple[float | None, bool]:
    """Return (retry_after_seconds, daily_quota_exhausted) from a Gemini 429 error body."""
    retry_after: float | None = None
    daily = False
    for detail in (body.get("error") or {}).get("details") or []:
        if not isinstance(detail, dict):
            continue
        delay = detail.get("retryDelay")
        if isinstance(delay, str):
            m = re.match(r"^\s*(\d+(?:\.\d+)?)s\s*$", delay)
            if m:
                retry_after = float(m.group(1))
        for v in detail.get("violations") or []:
            if isinstance(v, dict) and "PerDay" in str(v.get("quotaId", "")):
                daily = True
    return retry_after, daily


class ModelRetired(AIUnavailable):
    """Google no longer serves this model (HTTP 404)."""


def list_models(api_key: str, endpoint: str = ENDPOINT) -> list[dict]:
    """The Gemini models this key can ask for text, as Google lists them right now. Listing costs no quota."""
    req = urllib.request.Request(endpoint.split("/models/")[0] + "/models?pageSize=200",
                                 headers={"x-goog-api-key": api_key.strip()})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            listed = json.loads(resp.read().decode("utf-8")).get("models", [])
    except urllib.error.HTTPError as exc:
        if exc.code in (400, 401, 403):
            raise AIUnavailable("Gemini rejected the API key (check it in Settings)") from None
        raise AIUnavailable(f"Gemini HTTP error {exc.code}") from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise AIUnavailable(f"Gemini unreachable ({exc.__class__.__name__})") from None
    models = {}
    for m in listed:
        name = str(m.get("name", "")).removeprefix("models/")
        if (name.startswith("gemini-") and not NOT_FOR_TEXT.search(name)
                and "generateContent" in m.get("supportedGenerationMethods", [])):
            models[name] = str(m.get("displayName") or name)
    ranked = flash_models(list(models))
    order = [n for n in models if n.endswith("-latest")] + ranked + sorted(models)
    return [{"name": n, "label": models[n]} for n in dict.fromkeys(order)]


def flash_models(names: list[str]) -> list[str]:
    """Stable Flash and Flash-Lite model names, newest first; Flash before Flash-Lite of the same version."""
    found = [([-int(x) for x in m.group(1).split(".")], m.group(2) is not None, n)
             for n in names if (m := FLASH_RE.fullmatch(n))]
    return [n for *_, n in sorted(found)]


class GeminiProvider(AIProvider):
    name = "gemini"

    def __init__(self, api_key: str, model: str, endpoint: str = ENDPOINT,
                 cancel_event: threading.Event | None = None, notify: Callable[[str], None] | None = None) -> None:
        self.api_key = api_key.strip()
        self.chosen = model.strip() or DEFAULT_GEMINI_MODEL
        self.endpoint = endpoint
        self.cancel_event = cancel_event  # set when the job is cancelled: stop before asking the next model
        self.notify = notify or (lambda message: None)

    @property
    def models(self) -> list[str]:
        listed = self._listed_flash_models()
        below = listed.index(self.chosen) + 1 if self.chosen in listed else 0
        names = [self.chosen, *listed[below:], _last_good, *listed[:below], *BACKUP_MODELS]
        now = time.monotonic()
        return [m for m in dict.fromkeys(names) if m and _unusable_until.get(m, 0) <= now]

    def _listed_flash_models(self) -> list[str]:
        """The Flash models this key can use, asked once per run of the app."""
        global _flash_models
        if _flash_models is None:
            try:
                _flash_models = flash_models([m["name"] for m in list_models(self.api_key, self.endpoint)])
            except AIError:
                _flash_models = []  # the backup names above still work
        return _flash_models

    def available(self) -> bool:
        return bool(self.api_key)

    def generate_json(self, system: str, prompt: str, timeout_s: int = 60) -> dict:
        """Ask the configured model; when it is retired, busy or out of quota, ask the backup models, which
        have their own capacity and quota."""
        if not self.api_key:
            raise AIUnavailable("No Gemini API key configured")
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json", "maxOutputTokens": 8192},
        }
        models = self.models
        if not models:
            raise AIRateLimited("Gemini free-tier daily quota used up for every model this key can use", daily=True)
        _pace()
        busy: list[AIRateLimited] = []
        for i, model in enumerate(models):
            if self.cancel_event is not None and self.cancel_event.is_set():
                raise AIUnavailable("the job was cancelled")
            try:
                answer = self._request(model, body, timeout_s)
            except ModelRetired as exc:
                _unusable_until[model] = math.inf
                self._moving_on(exc, models[i + 1:])
                continue
            except AIRateLimited as exc:
                if exc.daily:
                    _unusable_until[model] = time.monotonic() + (exc.retry_after or 3600)
                    self._moving_on(exc, models[i + 1:])
                    continue
                busy.append(exc)
                if len(busy) == MAX_BUSY_MODELS_PER_REQUEST:
                    break
                self._moving_on(exc, models[i + 1:])
                continue
            global _last_good
            self.last_model = _last_good = model
            return answer
        if busy:
            raise busy[0]
        raise AIRateLimited("Gemini free-tier daily quota used up for every model this key can use", daily=True)

    def _moving_on(self, exc: AIError, rest: list[str]) -> None:
        if rest:
            self.notify(f"{exc}; trying {rest[0]}.")

    def _request(self, model: str, body: dict, timeout_s: int) -> dict:
        req = urllib.request.Request(
            self.endpoint.format(model=model),
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = ""
            error_body: dict = {}
            try:
                error_body = json.loads(exc.read().decode("utf-8"))
                detail = error_body.get("error", {}).get("status", "")
            except Exception:
                pass
            if exc.code == 429 or detail == "RESOURCE_EXHAUSTED":
                retry_after, daily = parse_rate_limit(error_body if isinstance(error_body, dict) else {})
                what = "daily quota used up" if daily else "rate limit reached"
                raise AIRateLimited(f"Gemini free-tier {what} for '{model}'", retry_after=retry_after,
                                    daily=daily) from None
            if exc.code in (500, 503, 504):
                raise AIRateLimited(f"Gemini model '{model}' is busy at Google right now", retry_after=BUSY_WAIT_S) from None
            if exc.code in (401, 403) or "API_KEY_INVALID" in json.dumps(error_body):
                raise AIUnavailable("Gemini rejected the API key (check it in Settings)") from None
            if exc.code == 404:
                raise ModelRetired(f"Gemini model '{model}' is no longer offered") from None
            raise AIUnavailable(f"Gemini HTTP error {exc.code} {detail}".strip()) from None
        except TimeoutError:
            raise AIRateLimited(f"Gemini model '{model}' did not answer within {timeout_s} s",
                                retry_after=BUSY_WAIT_S) from None
        except (urllib.error.URLError, OSError) as exc:
            raise AIUnavailable(f"Gemini unreachable ({exc.__class__.__name__})") from None
        except http.client.HTTPException as exc:
            raise AIBadResponse(f"Gemini's answer was incomplete ({exc.__class__.__name__})") from None
        except ValueError:  # not JSON, or not UTF-8
            raise AIBadResponse("Gemini returned a non-JSON HTTP body") from None
        try:
            candidate = payload["candidates"][0]
            if candidate.get("finishReason") in {"SAFETY", "RECITATION", "PROHIBITED_CONTENT"}:
                raise AIBadResponse(f"Gemini blocked the response ({candidate['finishReason']})")
            text = "".join(p.get("text", "") for p in candidate["content"]["parts"])
        except (KeyError, IndexError, TypeError, AttributeError):
            raise AIBadResponse("Unexpected Gemini response shape") from None
        return extract_json(text)
