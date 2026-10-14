from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

IssueKind = Literal[
    "fatal_error",
    "missing_file",
    "undefined_reference",
    "undefined_citation",
    "missing_package",
    "overfull_hbox",
    "underfull_hbox",
    "font_warning",
    "bibtex_error",
    "unicode_error",
    "other_warning",
]


class LogIssue(BaseModel):
    kind: IssueKind
    severity: Literal["error", "warning", "info"]
    message: str
    file: str | None = None
    line: int | None = None
    target: str | None = None
    amount_pt: float | None = None
    context: str = ""


class CompileResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    iteration: int = Field(ge=1, le=5)
    success: bool
    exit_code: int | None
    timed_out: bool = False
    cancelled: bool = False
    duration_seconds: float
    command: list[str] = Field(default_factory=list)
    pdf_path: str | None
    page_count: int | None = None
    log_path: str | None = None
    stdout_tail: str = ""
    stderr_tail: str = ""
    issues: list[LogIssue]

    @property
    def errors(self) -> list[LogIssue]:
        return [i for i in self.issues if i.severity == "error"]
