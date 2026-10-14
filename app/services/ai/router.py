"""Choose an AI provider, enforce the per-job call budget, and fall back cleanly.

Order: the user's provider (Gemini with their key, or Ollama), then Ollama as a
fallback when enabled, then None, which tells the calling agent to use its rules.

The router also keeps the job's agent trace: for every step, whether an AI agent
or the rules did the work, and why. A "full" job whose AI ran out (rate limit,
daily quota, or call budget) finishes as "partial" and says where it switched.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from app.services.ai.base import AIBadResponse, AIError, AIProvider, AIRateLimited, AIUnavailable
from app.services.ai.cache import JobAICache
from app.services.ai.gemini import GeminiProvider
from app.services.ai.ollama import OllamaProvider
from app.services.settings_store import MAX_AGENT_CALLS, UserSettings, redact

PARTIAL_MAX_CALLS = 3
MAX_RETRY_WAIT_S = 40.0
SHORT_WAIT_RETRIES = 2
# The fields of each agent's answer that must be lists. A string there would be read one letter at a time.
LIST_FIELDS = {
    "structure_outline": ("authors", "keywords", "headings"),
    "structure_review": ("authors", "keywords", "heading_levels", "notes"),
    "format_plan": ("wide_figures", "wide_tables", "drop_packages", "notes"),
    "repair_agent": ("actions",),
    "report_review": ("priorities",),
}


@dataclass
class AIUsageLog:
    calls: int = 0
    used_providers: list[str] = field(default_factory=list)
    models: list[str] = field(default_factory=list)
    fallbacks: list[str] = field(default_factory=list)


@dataclass
class TraceEntry:
    step: str
    actor: str  # ai | rules | tool
    provider: str | None = None
    note: str = ""


def check_shape(task: str, answer: object) -> None:
    """Raise AIBadResponse unless the answer is a JSON object with lists where the task expects them."""
    if not isinstance(answer, dict):
        raise AIBadResponse("the answer is not a JSON object")
    wrong = [f for f in LIST_FIELDS.get(task, ()) if answer.get(f) is not None and not isinstance(answer[f], list)]
    if wrong:
        raise AIBadResponse(f"the answer has the wrong shape ({', '.join(wrong)} should be a list)")


def build_providers(settings: UserSettings, level: str | None = None, cancel_event: threading.Event | None = None,
                    notify: Callable[[str], None] | None = None) -> list[AIProvider]:
    """off: none. Otherwise the chosen provider, plus Ollama as a fallback for Gemini when enabled."""
    level = level or settings.agentic_level
    providers: list[AIProvider] = []
    if level == "off":
        return providers
    if settings.ai_provider == "ollama":
        providers.append(OllamaProvider(settings.ollama_base_url, settings.ollama_model))
        return providers
    if settings.gemini_api_key:
        providers.append(GeminiProvider(settings.gemini_api_key, settings.gemini_model, cancel_event=cancel_event,
                                        notify=notify))
    if settings.ollama_enabled:
        providers.append(OllamaProvider(settings.ollama_base_url, settings.ollama_model))
    return providers


def call_budget(settings: UserSettings, level: str) -> int:
    if level == "off":
        return 0
    if level == "partial":
        return PARTIAL_MAX_CALLS
    return max(1, min(settings.max_agent_calls, MAX_AGENT_CALLS))


class AIRouter:
    def __init__(self, settings: UserSettings, max_calls: int | None = None, cache: JobAICache | None = None,
                 log: Callable[[str, str], None] | None = None, providers: list[AIProvider] | None = None,
                 level: str = "partial", cancel_event: threading.Event | None = None) -> None:
        self.settings = settings
        self.level = level if level in {"off", "partial", "full"} else "off"
        budget = call_budget(settings, self.level)
        self.max_calls = budget if max_calls is None else max(0, min(max_calls, budget))
        self.cache = cache or JobAICache()
        self.log = log or (lambda msg, level: None)
        if providers is None:
            providers = build_providers(settings, self.level, cancel_event, lambda msg: self.log(msg, "warning"))
        self.providers = providers
        self.cancel_event = cancel_event
        self.disabled: set[str] = set()
        self.usage = AIUsageLog()
        self.trace: list[TraceEntry] = []
        self.limit_hit = False
        self.limit_reason = ""
        self.last_failure = ""
        self.fallback_steps: list[str] = []
        self.switch_reason = ""  # why the first step had to use its rules
        self.wanted = False  # some step needed the AI
        self.answers = 0
        self.rejected = 0  # answers a step could not use

    # ------------------------------------------------------------------ state
    @property
    def enabled(self) -> bool:
        return bool(self.providers) and self.max_calls > 0

    @property
    def full(self) -> bool:
        return self.level == "full" and self.enabled

    @property
    def can_ask(self) -> bool:
        return self.enabled and self.remaining() > 0 and any(p.name not in self.disabled for p in self.providers)

    @property
    def mode_label(self) -> str:
        return "+".join(self.usage.used_providers) if self.usage.used_providers else "deterministic"

    @property
    def achieved_level(self) -> str:
        """What actually happened: off (no AI answer was used), partial, or full. Partial mode stays partial when
        no step needed the AI."""
        if self.level == "off":
            return "off"
        if self.answers <= self.rejected:
            return "partial" if self.level == "partial" and self.enabled and not self.wanted else "off"
        if self.level == "full" and self.fallback_steps:
            return "partial"
        return self.level

    def remaining(self) -> int:
        return self.max_calls - self.usage.calls

    # ------------------------------------------------------------------ trace
    def record(self, step: str, actor: str, note: str = "", provider: str | None = None) -> None:
        self.trace.append(TraceEntry(step=step, actor=actor, provider=provider, note=note[:300]))

    def fallback(self, step: str, reason: str = "") -> str:
        """An agent wanted the AI but had to use its rules instead. Returns the reason."""
        self.wanted = True
        if self.enabled:
            self._budget_left()
        why = reason or self.limit_reason or self.last_failure or "no AI answer was available"
        self.switch_reason = self.switch_reason or why
        if step not in self.fallback_steps:
            self.fallback_steps.append(step)
        self.record(step, "rules", f"Switched to rules: {why}")
        return why

    def reject(self, step: str, provider: str, why: str) -> str:
        """A step could not use the AI's answer (it failed a check) and used its rules instead."""
        self.rejected += 1
        return self.fallback(step, f"the answer from {provider} could not be used ({why})")

    def _budget_left(self) -> bool:
        if self.remaining() > 0:
            return True
        self._mark_limit(f"AI request limit ({self.max_calls}) reached")
        return False

    def _mark_limit(self, reason: str) -> None:
        if not self.limit_hit:
            self.limit_hit = True
            self.limit_reason = reason
            if self.level == "full":
                self.log(f"{reason[:1].upper()}{reason[1:]}. The remaining steps use rules, so this job becomes "
                         "partly agentic.", "warning")

    def _wait(self, seconds: float) -> bool:
        """Sleep, but stop early if the job is cancelled. Returns False when cancelled."""
        if self.cancel_event is not None:
            return not self.cancel_event.wait(seconds)
        time.sleep(seconds)
        return True

    @property
    def cancelled(self) -> bool:
        return self.cancel_event is not None and self.cancel_event.is_set()

    # ------------------------------------------------------------------ calls
    def ask(self, task: str, system: str, prompt: str) -> tuple[dict, str] | None:
        """Return (json_answer, provider_name) or None when no AI answer is available."""
        if not self.enabled:
            return None
        self.wanted = True
        key = JobAICache.key(task, system, prompt)
        cached = self.cache.get(key)
        if cached is not None:
            self.log(f"AI cache hit for {task}; no new request sent.", "info")
            self.answers += 1
            return cached["answer"], cached["provider"]
        for provider in self.providers:
            if provider.name in self.disabled:
                continue
            if self.cancelled:
                return None
            if not self._budget_left():
                self.log(f"AI request limit ({self.max_calls}) reached; continuing with rules.", "warning")
                return None
            if not provider.available():
                self.disabled.add(provider.name)
                self.last_failure = f"{provider.name} is not available"
                self.usage.fallbacks.append(f"{provider.name}: not available")
                self.log(f"{provider.name} is not available; trying the next option.", "warning")
                continue
            answer = self._call(provider, task, system, prompt)
            if answer is None:
                continue
            self.answers += 1
            self.cache.put(key, {"answer": answer, "provider": provider.name})
            if provider.name not in self.usage.used_providers:
                self.usage.used_providers.append(provider.name)
            model = provider.last_model
            if model and model not in self.usage.models:
                self.usage.models.append(model)
            who = f"{provider.name} ({model})" if model else provider.name
            self.log(f"{task}: answered by {who}, AI request {self.usage.calls} of {self.max_calls}.", "info")
            return answer, provider.name
        if self.providers and all(p.name in self.disabled for p in self.providers):
            self._mark_limit(self.last_failure or "no AI provider answered")
        self.log("No AI provider could answer; using rules for this step.", "warning")
        return None

    def _call(self, provider: AIProvider, task: str, system: str, prompt: str) -> dict | None:
        """One request. A short wait (busy models, per-minute rate limit) is waited out up to twice; any other
        error, or an answer of the wrong shape, ends the attempt (see _give_up)."""
        retries = 0
        while True:
            self.usage.calls += 1
            try:
                answer = provider.generate_json(system, prompt)
                check_shape(task, answer)
                return answer
            except AIRateLimited as exc:
                short_wait = exc.retry_after is not None and exc.retry_after <= MAX_RETRY_WAIT_S and not exc.daily
                if not (short_wait and retries < SHORT_WAIT_RETRIES and self.remaining() > 0):
                    return self._give_up(provider, exc)
                retries += 1
                wait = float(exc.retry_after) + 1
                self.log(f"{provider.name}: {redact(str(exc), self.settings)}; waiting {wait:.0f}s and trying again.",
                         "warning")
                if not self._wait(wait):
                    return None
            except AIError as exc:
                return self._give_up(provider, exc)
            except Exception as exc:  # a provider bug must not stop the job
                return self._give_up(provider, AIBadResponse(f"unexpected error ({exc.__class__.__name__})"))

    def _give_up(self, provider: AIProvider, exc: AIError) -> None:
        """A busy moment or one bad answer only costs this step; a used-up daily quota or a provider that cannot
        work (no key, key rejected, unreachable) switches the provider off for the rest of the job."""
        msg = redact(str(exc), self.settings)
        self.last_failure = msg
        self.usage.fallbacks.append(f"{provider.name}: {msg}")
        if isinstance(exc, AIUnavailable) or getattr(exc, "daily", False):
            self.disabled.add(provider.name)
            self.log(f"{provider.name} failed: {msg}. Falling back.", "warning")
        else:
            self.log(f"{provider.name} could not answer this time: {msg}. This step uses rules; later steps "
                     "ask again.", "warning")
