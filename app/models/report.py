from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.qa import RepairAction

DISCLAIMER = (
    "Paper Forge checks only the rules configured for this venue. Always read the venue's "
    "current call for papers and author kit before submitting."
)


class CheckResult(BaseModel):
    check_id: str
    type: str
    status: Literal["passed", "warning", "failed", "manual_review", "style"]
    message: str
    details: list[str] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)


class ReportSummary(BaseModel):
    checks_total: int
    passed: int
    warnings: int
    failed: int
    manual_review: int
    style: int = 0  # writing-style suggestions; they do not change the overall status
    changes: int = 0  # corrections Paper Forge made to the author's text
    page_count: int | None = None
    compile_iterations: int = 0


class AgentStep(BaseModel):
    step: str
    actor: Literal["ai", "rules", "tool"]
    provider: str | None = None
    note: str = ""


class AIUsage(BaseModel):
    level_requested: Literal["off", "partial", "full"] = "off"
    level_achieved: Literal["off", "partial", "full"] = "off"
    mode: Literal["deterministic", "gemini", "ollama", "gemini+ollama", "ollama+gemini"] = "deterministic"
    models: list[str] = Field(default_factory=list)
    calls: int = Field(default=0, ge=0, le=30)
    limit_hit: bool = False
    limit_reason: str = ""
    steps: list[AgentStep] = Field(default_factory=list)
    fallbacks: list[str] = Field(default_factory=list)


class AgentReview(BaseModel):
    """Advice written by the Report agent in Full mode. It never changes a check result."""

    provider: str
    summary: str
    priorities: list[str] = Field(default_factory=list)


class ComplianceReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    job_id: str
    venue_id: str
    venue_name: str = ""
    generated_at: str
    overall_status: Literal["compliant", "needs_attention", "failed"]
    summary: ReportSummary
    passed: list[CheckResult] = Field(default_factory=list)
    warnings: list[CheckResult] = Field(default_factory=list)
    failed: list[CheckResult] = Field(default_factory=list)
    manual_review: list[CheckResult] = Field(default_factory=list)
    style: list[CheckResult] = Field(default_factory=list)
    changes: list[str] = Field(default_factory=list)
    repairs: list[RepairAction] = Field(default_factory=list)
    ai_usage: AIUsage = Field(default_factory=AIUsage)
    agent_review: AgentReview | None = None
    disclaimer: str = DISCLAIMER
