"""Check-type registry. Venue JSON files choose which checks run and with what parameters.

To add a new check type: write ``def my_check(ctx, check) -> CheckResult`` in a
module here, decorate it with ``@register("my_check")``, and add the name to
``CheckType`` in app/models/venue.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from app.models.compile import CompileResult
from app.models.latex import LaTeXProject
from app.models.manuscript import ManuscriptStructure
from app.models.qa import RepairAction
from app.models.report import CheckResult
from app.models.venue import VenueCheck, VenueSpec


@dataclass
class CheckContext:
    spec: VenueSpec
    manuscript: ManuscriptStructure
    project: LaTeXProject
    compile_result: CompileResult | None
    repairs: list[RepairAction] = field(default_factory=list)
    removed_citations: list[str] = field(default_factory=list)
    placeholder_figures: list[str] = field(default_factory=list)

    @property
    def main_tex(self) -> str:
        root = Path(self.project.root_dir)
        text = (root / self.project.main_file).read_text(encoding="utf-8", errors="replace")
        for sec in self.project.section_files:
            p = root / sec
            if p.exists():
                text += "\n" + p.read_text(encoding="utf-8", errors="replace")
        return text

    @property
    def pdf_path(self) -> Path | None:
        if self.compile_result and self.compile_result.pdf_path and self.compile_result.success:
            return Path(self.compile_result.pdf_path)
        return None


CheckFn = Callable[[CheckContext, VenueCheck], CheckResult]
CHECKS: dict[str, CheckFn] = {}


def register(name: str) -> Callable[[CheckFn], CheckFn]:
    def deco(fn: CheckFn) -> CheckFn:
        CHECKS[name] = fn
        return fn

    return deco


def result(check: VenueCheck, ok: bool, message: str, details: list[str] | None = None,
           evidence: dict | None = None) -> CheckResult:
    """Build a CheckResult; failures take the check's configured severity."""
    if ok:
        status = "passed"
    elif check.severity == "error":
        status = "failed"
    elif check.severity == "warning":
        status = "warning"
    elif check.severity == "style":
        status = "style"
    else:
        status = "manual_review"
    return CheckResult(check_id=check.id, type=check.type, status=status, message=message,
                       details=details or [], evidence=evidence or {})


def run_checks(ctx: CheckContext) -> list[CheckResult]:
    results = []
    for check in ctx.spec.checks:
        fn = CHECKS.get(check.type)
        if fn is None:
            results.append(CheckResult(check_id=check.id, type=check.type, status="manual_review",
                                       message=f"No automatic check for '{check.type}'; review manually."))
            continue
        try:
            results.append(fn(ctx, check))
        except Exception as exc:  # a broken check must not hide the others
            results.append(CheckResult(check_id=check.id, type=check.type, status="manual_review",
                                       message=f"{check.description}: could not be checked automatically ({exc.__class__.__name__}).",
                                       ))
    return results


# Importing the check modules registers their checks. They import this module, so this must come last.
from app.validators import log_checks, pdf_checks, source_checks, style_checks  # noqa: E402, F401
