"""Checks based on the final compile log and on repairs that changed content."""

from __future__ import annotations

import unicodedata

from app.models.report import CheckResult
from app.models.venue import VenueCheck
from app.validators.registry import CheckContext, register, result


@register("compile_success")
def compile_success(ctx: CheckContext, check: VenueCheck) -> CheckResult:
    cr = ctx.compile_result
    if cr is None:
        return result(check, False, "Compilation did not run.")
    if cr.success:
        return result(check, True, f"Compiled to PDF in {cr.iteration} pass(es) of the compile-repair loop.",
                      evidence={"iterations": cr.iteration, "pages": cr.page_count})
    errors = [i.message + (f" (line {i.line})" if i.line else "") for i in cr.issues if i.severity == "error"]
    return result(check, False, "LaTeX compilation failed.", details=errors[:10])


@register("figures_resolved")
def figures_resolved(ctx: CheckContext, check: VenueCheck) -> CheckResult:
    problems = []
    for name in ctx.placeholder_figures:
        problems.append(f"{name}: file missing, replaced by a placeholder box")
    for name in ctx.project.unconverted_figures:
        problems.append(f"{name}: format could not be embedded, replaced by a placeholder box")
    if ctx.compile_result:
        for i in ctx.compile_result.issues:
            if i.kind == "missing_file" and i.target and i.target not in " ".join(problems):
                problems.append(f"{i.target}: not found")
    if problems:
        return result(check, False, f"{len(problems)} figure problem(s).", details=problems)
    n = len(ctx.project.figure_files)
    return result(check, True, f"All {n} figure file(s) found and embedded.")


@register("citations_resolved")
def citations_resolved(ctx: CheckContext, check: VenueCheck) -> CheckResult:
    undefined = []
    if ctx.compile_result:
        undefined = sorted({i.target for i in ctx.compile_result.issues if i.kind == "undefined_citation" and i.target})
    details = [f"\\cite{{{k}}} removed: no bibliography entry" for k in ctx.removed_citations]
    details += [f"{k}: still undefined" for k in undefined]
    if details:
        return result(check, False, f"{len(ctx.removed_citations) + len(undefined)} citation(s) without a bibliography entry.",
                      details=details)
    return result(check, True, "Every citation has a bibliography entry.")


@register("references_resolved")
def references_resolved(ctx: CheckContext, check: VenueCheck) -> CheckResult:
    if not ctx.compile_result:
        return result(check, False, "Not checked: compilation did not run.")
    undefined = sorted({i.target for i in ctx.compile_result.issues if i.kind == "undefined_reference" and i.target})
    if undefined:
        return result(check, False, f"{len(undefined)} undefined \\ref label(s); they print as '??'.", details=undefined)
    return result(check, True, "All cross-references resolve.")


@register("overfull_boxes")
def overfull_boxes(ctx: CheckContext, check: VenueCheck) -> CheckResult:
    if not ctx.compile_result:
        return result(check, False, "Not checked: compilation did not run.")
    threshold = float(check.params.get("threshold_pt", 5))
    big = [i for i in ctx.compile_result.issues if i.kind == "overfull_hbox" and (i.amount_pt or 0) > threshold]
    if big:
        details = [f"{i.amount_pt:.1f}pt too wide" + (f" near line {i.line}" if i.line else "") for i in big[:15]]
        return result(check, False, f"{len(big)} line(s) stick into the margin by more than {threshold:g}pt.", details=details)
    return result(check, True, f"No overfull boxes above {threshold:g}pt.")


def _shown(char: str) -> str:
    """'é', or the name of a character that does not print alone: COMBINING TILDE."""
    return unicodedata.name(char[0], "a character") if unicodedata.combining(char[0]) else f"'{char}'"


@register("missing_glyphs")
def missing_glyphs(ctx: CheckContext, check: VenueCheck) -> CheckResult:
    if not ctx.compile_result:
        return result(check, False, "Not checked: compilation did not run.")
    chars = sorted({i.target for i in ctx.compile_result.issues if i.kind == "font_warning" and i.target})
    if chars:
        return result(check, False, f"{len(chars)} character(s) are missing from the PDF: the font has no glyph for them.",
                      details=[f"{_shown(c)} (U+{ord(c[0]):04X}) was left out; replace it with a LaTeX command"
                               for c in chars])
    return result(check, True, "Every character has a glyph in the font.")
