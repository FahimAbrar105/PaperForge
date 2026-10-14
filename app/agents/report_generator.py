"""Step 7 - Report Generator: ComplianceReport as JSON, Markdown and HTML.

The check results always come from the venue's rule checks. In Full agentic
mode a Report agent also writes a short review for the author (a summary and
the most important next actions); it is labelled as AI advice and never
changes a check result.
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path

from app.agents.base import StepContext
from app.models.compile import CompileResult
from app.models.latex import LaTeXProject
from app.models.manuscript import ManuscriptStructure
from app.models.qa import RepairAction
from app.models.report import AgentReview, CheckResult, ComplianceReport, ReportSummary
from app.models.venue import VenueSpec
from app.validators.registry import CheckContext, run_checks

STEP = "Report Generator"
LEVEL_LABEL = {"off": "Off (rules only)", "partial": "Partial", "full": "Full"}
REVIEW_SYSTEM = (
    "You are the Report agent of a paper-formatting pipeline. You explain a compliance report to the author "
    "in plain words. Be concrete and brief, mention only problems listed in the input, and do not invent any. "
    "Manual-review items are reminders, not problems: phrase them as things to check. Changes made are already "
    "done; never ask the author to make them. Return only JSON."
)
REVIEW_PROMPT = """Compliance report for a paper formatted for {venue}:
{data}

Return JSON: {{"summary": "<2-3 sentences: is the paper ready, and what matters most>",
 "priorities": ["<one concrete action for the author>", "... at most 6: failed checks first, then warnings, then style
 suggestions, then reminders"]}}"""
STATUS_TEXT = {
    "compliant": "Layout checks passed",
    "needs_attention": "PDF produced, but some items need attention",
    "failed": "Some required checks failed",
}


def build_report(job_id: str, spec: VenueSpec, manuscript: ManuscriptStructure, project: LaTeXProject,
                 compile_result: CompileResult | None, repairs: list[RepairAction], removed_citations: list[str],
                 placeholder_figures: list[str], iterations: int,
                 extra_manual: list[str] | None = None) -> ComplianceReport:
    """Run the venue's checks. The orchestrator fills in ``ai_usage`` once the review agent has run."""
    ctx = CheckContext(spec=spec, manuscript=manuscript, project=project, compile_result=compile_result,
                       repairs=repairs, removed_citations=removed_citations, placeholder_figures=placeholder_figures)
    results = run_checks(ctx)
    manual_extra = [*spec.manual_review_items, *(extra_manual or [])]
    for idx, item in enumerate(dict.fromkeys(manual_extra)):
        results.append(CheckResult(check_id=f"manual_note_{idx + 1}", type="manual", status="manual_review", message=item))
    passed = [r for r in results if r.status == "passed"]
    warnings = [r for r in results if r.status == "warning"]
    failed = [r for r in results if r.status == "failed"]
    manual = [r for r in results if r.status == "manual_review"]
    style = [r for r in results if r.status == "style"]
    automated_total = len(passed) + len(warnings) + len(failed)
    if failed:
        overall = "failed"
    elif warnings:
        overall = "needs_attention"
    else:
        overall = "compliant"
    return ComplianceReport(
        job_id=job_id,
        venue_id=spec.venue_id,
        venue_name=spec.display_name,
        generated_at=datetime.now(timezone.utc).isoformat(),
        overall_status=overall,
        summary=ReportSummary(checks_total=automated_total, passed=len(passed), warnings=len(warnings),
                              failed=len(failed), manual_review=len(manual), style=len(style),
                              changes=len(project.changes),
                              page_count=compile_result.page_count if compile_result else None,
                              compile_iterations=iterations),
        passed=passed, warnings=warnings, failed=failed, manual_review=manual, style=style, changes=project.changes,
        repairs=repairs,
    )


def review(ctx: StepContext, report: ComplianceReport) -> None:
    """Full agentic mode: ask the Report agent for a short review of the results."""
    ai = ctx.ai
    if ai is None or not ai.full:
        if ai is not None:
            ai.record(STEP, "rules", "Report built from the venue's rule checks.")
        return
    data = {
        "overall_status": report.overall_status,
        "pages": report.summary.page_count,
        "failed": [c.message for c in report.failed][:15],
        "warnings": [c.message for c in report.warnings][:15],
        "changes_made": report.changes[:15],
        "style_suggestions": [c.message for c in report.style][:15],
        "manual_review": [c.message for c in report.manual_review][:15],
        "repairs": [a.action for a in report.repairs][:15],
    }
    answer = ai.ask("report_review", REVIEW_SYSTEM,
                    REVIEW_PROMPT.format(venue=report.venue_name, data=json.dumps(data, ensure_ascii=False))) \
        if ai.can_ask else None
    if not answer:
        ctx.log(STEP, f"The report has no agent review: {ai.fallback(STEP)}.", "warning")
        return
    reply, provider = answer
    summary = " ".join(str(reply.get("summary", "")).split())[:800]
    listed = reply.get("priorities")
    priorities = [" ".join(str(p).split())[:240] for p in (listed if isinstance(listed, list) else [])[:6]
                  if str(p).strip()]
    if not summary and not priorities:
        ai.reject(STEP, provider, "its review was empty")
        return
    report.agent_review = AgentReview(provider=provider, summary=summary, priorities=priorities)
    ai.record(STEP, "ai", "Wrote the review and next steps for the author.", provider)
    ctx.log(STEP, f"Report agent ({provider}) wrote a review with {len(priorities)} next step(s).", "success")


def agentic_line(r: ComplianceReport) -> str:
    u = r.ai_usage
    text = f"Agentic mode: {LEVEL_LABEL[u.level_requested]}"
    if u.level_requested == "off":
        return text
    ai_steps = sum(s.actor == "ai" for s in u.steps)
    if u.level_achieved == "partial" and not ai_steps:
        return f"{text}, result: no step needed the AI, so the rules did everything"
    done = f"the AI did {ai_steps} step(s)" if ai_steps else "no AI answer could be used"
    models = f" to {', '.join(u.models)}" if u.models else ""
    text += f", result: {LEVEL_LABEL[u.level_achieved]}: {done} ({u.calls} AI request(s){models})"
    if u.limit_hit:
        text += f"; limit reached: {u.limit_reason}"
    return text


def counts(r: ComplianceReport) -> str:
    s = r.summary
    return (f"{s.passed} passed, {s.warnings} warnings, {s.failed} failed, {s.changes} change(s) made, "
            f"{s.style} style suggestion(s), {s.manual_review} for manual review")


def to_markdown(r: ComplianceReport) -> str:
    lines = [f"# Compliance report: {r.venue_name}", "",
             f"**Overall:** {STATUS_TEXT[r.overall_status]} ({r.overall_status})  ",
             f"**Job:** {r.job_id}  ", f"**Generated:** {r.generated_at}  ",
             f"**Pages:** {r.summary.page_count if r.summary.page_count is not None else 'n/a'}  ",
             f"**Compile passes:** {r.summary.compile_iterations}  ",
             f"**{agentic_line(r)}**", "",
             f"{counts(r)}.", ""]
    if r.agent_review:
        lines += [f"## Agent review (AI advice from {r.agent_review.provider})", "", r.agent_review.summary, ""]
        lines += [f"{i}. {p}" for i, p in enumerate(r.agent_review.priorities, 1)]
        lines.append("")

    def section(title: str, items: list[CheckResult]) -> None:
        lines.append(f"## {title} ({len(items)})")
        lines.append("")
        if not items:
            lines.append("_None._")
        for c in items:
            lines.append(f"- **{c.message}**" + (f" _({c.check_id})_" if not c.check_id.startswith("manual_note") else ""))
            for d in c.details:
                lines.append(f"  - {d}")
        lines.append("")

    section("Failed checks", r.failed)
    section("Warnings", r.warnings)
    lines += [f"## Changes Paper Forge made ({len(r.changes)})", ""]
    lines += [f"- {c}" for c in r.changes] or ["_None._"]
    lines.append("")
    section("Style suggestions", r.style)
    section("Manual review", r.manual_review)
    section("Passed checks", r.passed)
    lines.append(f"## Automatic repairs ({len(r.repairs)})")
    lines.append("")
    if not r.repairs:
        lines.append("_None needed._")
    for a in r.repairs:
        lines.append(f"- Pass {a.iteration} [{a.source}]: {a.action}")
    if r.ai_usage.steps and r.ai_usage.level_requested != "off":
        lines += ["", "## Who did each step", ""]
        lines += [f"- {s.step}: {s.actor}{' (' + s.provider + ')' if s.provider else ''}"
                  f"{' - ' + s.note if s.note else ''}" for s in r.ai_usage.steps]
    if r.ai_usage.fallbacks:
        lines += ["", "## AI fallbacks", ""] + [f"- {f}" for f in r.ai_usage.fallbacks]
    lines += ["", "---", r.disclaimer, ""]
    return "\n".join(lines)


THEME_SCRIPT = ('(function(){var t;try{t=localStorage.getItem("pf-theme")}catch(e){}if(t!=="dark"&&t!=="light")'
                't=window.matchMedia&&matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light";'
                'document.documentElement.setAttribute("data-theme",t)})();')


def to_html(r: ComplianceReport) -> str:
    e = html.escape
    color = {"compliant": "var(--green)", "needs_attention": "var(--amber)", "failed": "var(--red)"}[r.overall_status]

    def block(title: str, items: list[CheckResult], cls: str) -> str:
        rows = "".join(
            f"<li><strong>{e(c.message)}</strong>"
            + ("<ul>" + "".join(f"<li>{e(d)}</li>" for d in c.details) + "</ul>" if c.details else "")
            + "</li>" for c in items) or "<li class='none'>None</li>"
        return f"<section class='{cls}'><h2>{e(title)} ({len(items)})</h2><ul>{rows}</ul></section>"

    changes = "".join(f"<li>{e(c)}</li>" for c in r.changes) or "<li class='none'>None</li>"
    repairs = "".join(f"<li>Pass {a.iteration} <code>{e(a.source)}</code>: {e(a.action)}</li>" for a in r.repairs) \
        or "<li class='none'>None needed</li>"
    review_html = ""
    if r.agent_review:
        items = "".join(f"<li>{e(p)}</li>" for p in r.agent_review.priorities)
        review_html = (f"<section class='review'><h2>Agent review <small>(AI advice from {e(r.agent_review.provider)})"
                       f"</small></h2><p>{e(r.agent_review.summary)}</p>" + (f"<ol>{items}</ol>" if items else "")
                       + "</section>")
    steps_html = ""
    if r.ai_usage.steps and r.ai_usage.level_requested != "off":
        rows = "".join(f"<tr><td>{e(s.step)}</td><td><code>{e(s.actor)}</code>{' ' + e(s.provider) if s.provider else ''}"
                       f"</td><td>{e(s.note)}</td></tr>" for s in r.ai_usage.steps)
        steps_html = (f"<section><h2>Who did each step</h2><table><tr><th>Step</th><th>Done by</th><th>Note</th></tr>"
                      f"{rows}</table></section>")
    if r.ai_usage.fallbacks:
        items = "".join(f"<li>{e(f)}</li>" for f in r.ai_usage.fallbacks)
        steps_html += f"<section><h2>AI fallbacks</h2><ul>{items}</ul></section>"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Compliance report</title>
<script>{THEME_SCRIPT}</script>
<style>
:root{{color-scheme:light;--paper:#f7f6f2;--surface:#fdfcf9;--ink:#161616;--ink-soft:#5f605d;--rule:#d7d5ce;
--cobalt:#2057d4;--green:#1d7a51;--amber:#8a5414;--red:#b53b35;--violet:#6a4bb8}}
:root[data-theme="dark"]{{color-scheme:dark;--paper:#171614;--surface:#1e1d1a;--ink:#ecebe6;--ink-soft:#a8a69e;
--rule:#33312d;--cobalt:#86a6f4;--green:#5fc192;--amber:#e1a457;--red:#ef8a82;--violet:#b9a4f2}}
body{{font:15px/1.55 'Segoe UI',Arial,sans-serif;max-width:860px;margin:2rem auto;padding:0 16px;color:var(--ink);background:var(--paper)}}
h1,h2{{font-family:Georgia,'Times New Roman',serif;font-weight:400}} h1{{font-size:1.9rem;line-height:1.15}} h2{{font-size:1.2rem;margin-top:1.6rem}}
.badge{{display:inline-block;padding:.3rem .8rem;border-radius:999px;color:var(--paper);background:{color};font-weight:600}}
.meta{{color:var(--ink-soft);font-size:.92rem}} section{{border-left:4px solid var(--rule);padding-left:1rem}}
.failed{{border-color:var(--red)}} .warn{{border-color:var(--amber)}} .manual{{border-color:var(--violet)}} .passed{{border-color:var(--green)}}
.style{{border-color:var(--cobalt)}} .changes{{border-color:var(--green)}}
li{{margin:.25rem 0}} .none{{color:var(--ink-soft);list-style:none}} code{{background:var(--surface);border:1px solid var(--rule);padding:0 .3rem;border-radius:4px}}
footer{{margin-top:2rem;color:var(--ink-soft);font-size:.85rem}} .review{{border-color:var(--cobalt)}}
table{{border-collapse:collapse;font-size:.9rem}} td,th{{text-align:left;padding:.25rem .6rem;border-bottom:1px solid var(--rule);vertical-align:top}}
</style></head><body>
<h1>Compliance report: {e(r.venue_name)}</h1>
<p><span class="badge">{e(STATUS_TEXT[r.overall_status])}</span></p>
<p class="meta">Job {e(r.job_id)} &middot; {e(r.generated_at)} &middot; Pages: {r.summary.page_count if r.summary.page_count is not None else 'n/a'}
&middot; Compile passes: {r.summary.compile_iterations}</p>
<p class="meta">{e(agentic_line(r))}</p>
<p>{e(counts(r))}.</p>
{review_html}
{block("Failed checks", r.failed, "failed")}
{block("Warnings", r.warnings, "warn")}
<section class='changes'><h2>Changes Paper Forge made ({len(r.changes)})</h2><ul>{changes}</ul></section>
{block("Style suggestions", r.style, "style")}
{block("Manual review", r.manual_review, "manual")}
{block("Passed checks", r.passed, "passed")}
<section><h2>Automatic repairs ({len(r.repairs)})</h2><ul>{repairs}</ul></section>
{steps_html}
<footer>{e(r.disclaimer)}</footer>
</body></html>
"""


def run(ctx: StepContext, report: ComplianceReport) -> dict[str, Path]:
    final = ctx.workspace.final
    paths = {
        "json": final / "compliance_report.json",
        "md": final / "compliance_report.md",
        "html": final / "compliance_report.html",
    }
    paths["json"].write_text(report.model_dump_json(indent=2), encoding="utf-8")
    paths["md"].write_text(to_markdown(report), encoding="utf-8")
    paths["html"].write_text(to_html(report), encoding="utf-8")
    s = report.summary
    ctx.log(STEP, f"{STATUS_TEXT[report.overall_status]}: {counts(report)}",
            {"compliant": "success", "needs_attention": "warning", "failed": "error"}[report.overall_status])
    return paths
