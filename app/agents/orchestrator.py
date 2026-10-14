"""Central orchestrator. The only component that calls the pipeline steps, in order:

1 Upload Handler (done by the route before queueing) -> 2 Venue Analyst ->
3 Content Structurer -> 4 LaTeX Formatter -> [5 Compiler <-> 6 QA & Repair] x <=5 ->
7 Report Generator -> final outputs.

Steps never talk to each other; each takes inputs and returns outputs, and the
orchestrator persists status and the live event log after every step.

Agentic level (chosen per job): in "full" mode the Content Structurer, LaTeX
Formatter, QA & Repair and Report Generator are driven by an AI agent; Upload
Handler and Venue Analyst stay rule-based (file safety and verified venue rules)
and the Compiler is the Tectonic tool. When the AI limit is reached, the
remaining steps use their rules and the job finishes as partly agentic.
"""

from __future__ import annotations

import copy
import logging
import shutil
import traceback
from pathlib import Path

from app.agents import compiler_agent, content_structurer, latex_formatter, qa_repair, report_generator, venue_analyst
from app.agents.base import JobCancelled, StepContext, StepError
from app.models.compile import CompileResult
from app.models.job import FinalOutput, JobStatus
from app.models.latex import LaTeXProject
from app.models.report import AgentStep, AIUsage, ComplianceReport
from app.models.venue import VenueSpec
from app.parsers.latex_parser import plain_title
from app.services.ai.cache import JobAICache
from app.services.ai.router import AIRouter
from app.services.job_store import JobStore
from app.services.settings_store import UserSettings, redact
from app.services.venue_registry import VenueRegistry
from app.services.workspace import zip_latex_project

log = logging.getLogger("paperforge.orchestrator")
LEVEL_TEXT = {"off": "agentic mode Off (rules only)", "partial": "agentic mode Partial",
              "full": "agentic mode Full"}


class Orchestrator:
    def __init__(self, ctx: StepContext, store: JobStore, registry: VenueRegistry, user_settings: UserSettings,
                 providers: list | None = None) -> None:
        self.ctx = ctx
        self.store = store
        self.registry = registry
        self.user_settings = user_settings
        self.providers = providers  # None: built from the user's settings (tests pass stubs)

    def _step(self, name: str) -> None:
        self.ctx.check_cancelled()
        self.store.update(self.ctx.job_id, current_step=name)

    def _usage(self, level: str) -> AIUsage:
        ai = self.ctx.ai
        mode = ai.mode_label if ai.mode_label in {"gemini", "ollama", "gemini+ollama", "ollama+gemini"} else "deterministic"
        return AIUsage(level_requested=level, level_achieved=ai.achieved_level, mode=mode, models=ai.usage.models,
                       calls=min(ai.usage.calls, 30), limit_hit=ai.limit_hit, limit_reason=ai.limit_reason,
                       steps=[AgentStep(step=t.step, actor=t.actor, provider=t.provider, note=t.note) for t in ai.trace],
                       fallbacks=ai.usage.fallbacks)

    def _log_agentic_summary(self, usage: AIUsage) -> None:
        if usage.level_requested == "off":
            return
        ai = self.ctx.ai
        ai_steps = [s.step for s in usage.steps if s.actor == "ai"]
        if usage.level_achieved == "full":
            msg = f"Fully agentic: {len(ai_steps)} step(s) were handled by the AI agents ({usage.calls} request(s))."
            level = "success"
        elif usage.level_requested == "full" and usage.level_achieved == "partial":
            msg = (f"Partly agentic: {usage.limit_reason or ai.switch_reason}. "
                   f"Rules took over at: {', '.join(ai.fallback_steps)}.")
            level = "warning"
        elif usage.level_achieved == "partial" and not ai_steps:
            msg = "Partial mode: no step needed the AI, so the rules did everything."
            level = "info"
        elif usage.level_achieved == "partial":
            msg = f"Partial mode: the AI helped in {len(ai_steps)} step(s) ({usage.calls} request(s))."
            level = "info"
        else:
            why = usage.limit_reason or ai.switch_reason or ai.last_failure or "no AI provider is set up"
            msg = f"No AI answer was used in this job ({why}); every step ran on rules."
            level = "warning"
        if usage.models:
            msg += f" {'Models' if len(usage.models) > 1 else 'Model'} used: {', '.join(usage.models)}."
        self.ctx.log("Orchestrator", msg, level)

    def run(self) -> None:
        ctx = self.ctx
        job = self.store.get(ctx.job_id)
        if job is None:
            return
        self.store.update(ctx.job_id, status=JobStatus.running)
        level = job.agentic_level if job.agentic_level in LEVEL_TEXT else "off"
        max_calls = ctx.settings.max_ai_calls_per_job if level == "partial" else None
        ctx.ai = AIRouter(self.user_settings, max_calls, cache=JobAICache(ctx.workspace.logs / "ai_cache.json"),
                          log=lambda msg, lvl: ctx.log("AI", msg, lvl), level=level, cancel_event=ctx.cancel_event,
                          providers=self.providers)
        ai = ctx.ai
        if level != "off" and not ai.enabled:
            ctx.log("Orchestrator", f"{LEVEL_TEXT[level]} was chosen, but no AI provider is set up "
                                    "(add a Gemini key in Settings). Running with rules only.", "warning")
        provider_text = f" via {', '.join(p.name for p in ai.providers)}, up to {ai.max_calls} AI requests" if ai.enabled else ""
        ctx.log("Orchestrator", f"Job started: {len(job.files)} file(s), venue {job.venue_id}, "
                                f"{LEVEL_TEXT[level if ai.enabled else 'off']}{provider_text}")
        ai.record("Upload Handler", "rules", "File types, sizes and contents are always checked by rules, for safety.")
        try:
            self._step("Venue Analyst")
            spec = venue_analyst.run(ctx, self.registry, job.camera_ready)
            ai.record("Venue Analyst", "rules", "Venue rules come from the verified venue file and template.")

            self._step("Content Structurer")
            manuscript = content_structurer.run(ctx, job.files)
            if manuscript.title:
                self.store.update(ctx.job_id, title=plain_title(manuscript)[:200])

            self._step("LaTeX Formatter")
            project, formatter_notes = latex_formatter.run(ctx, manuscript, spec)

            result, state, iterations = self._compile_and_repair(project, spec)

            self._step("Report Generator")
            report = report_generator.build_report(
                ctx.job_id, spec, manuscript, project, result, state.actions, state.removed_citations,
                state.placeholder_figures, iterations, extra_manual=[*manuscript.source.warnings, *formatter_notes],
            )
            report_generator.review(ctx, report)
            report.ai_usage = self._usage(level)  # after the review, so the review agent's step is included
            paths = report_generator.run(ctx, report)
            self.store.update(ctx.job_id, agentic_achieved=report.ai_usage.level_achieved)
            self._log_agentic_summary(report.ai_usage)
            self._save_outputs(result, report, paths)
        except JobCancelled:
            self.store.update(ctx.job_id, status=JobStatus.cancelled, current_step="Cancelled")
            ctx.log("Orchestrator", "Job cancelled.", "warning")
        except StepError as exc:
            msg = redact(str(exc), self.user_settings)
            self.store.update(ctx.job_id, status=JobStatus.failed, error=msg)
            ctx.log("Orchestrator", msg, "error")
        except Exception as exc:  # unexpected bug: keep the app alive, record a readable error
            msg = redact(f"Unexpected error: {exc.__class__.__name__}: {exc}", self.user_settings)
            (ctx.workspace.logs / "traceback.txt").write_text(redact(traceback.format_exc(), self.user_settings),
                                                             encoding="utf-8")
            log.exception("Job %s crashed", ctx.job_id)
            self.store.update(ctx.job_id, status=JobStatus.failed, error=msg)
            ctx.log("Orchestrator", msg + " (details in logs/traceback.txt)", "error")

    def _compile_and_repair(self, project: LaTeXProject, spec: VenueSpec
                            ) -> tuple[CompileResult, qa_repair.RepairState, int]:
        """Compile, let QA & Repair fix what it can, and compile again, up to the configured number of passes."""
        ctx = self.ctx
        # The warm-up allows downloads from the first compile on, so every package lands in the cache.
        state = qa_repair.RepairState(allow_network=ctx.data.get("allow_network", False))
        repairer = qa_repair.Repairer(ctx, project, spec, state)
        max_passes = max(1, min(ctx.settings.max_repair_iterations, 5))
        good = None  # main.tex and the repair state of the last pass that made a PDF
        for iteration in range(1, max_passes + 1):
            self._step(f"Compiler (pass {iteration})")
            result = self._compile(project, iteration, state)
            ctx.ai.record(f"Compiler (pass {iteration})", "tool",
                          "Tectonic compiled to PDF." if result.success else "Tectonic could not produce a PDF.")
            if result.success:
                good = (Path(project.root_dir, project.main_file).read_text(encoding="utf-8"), copy.deepcopy(state))
            elif good:
                result = self._undo_last_repairs(project, *good, state, iteration)
                break
            self._step(f"QA & Repair (pass {iteration})")
            if not qa_repair.run(ctx, repairer, result, iteration):
                break
            if iteration == max_passes:
                ctx.log("QA & Repair", f"Reached the limit of {max_passes} repair passes; compiling once more "
                                       "with the last fixes.", "warning")
                self._step("Compiler (final pass)")
                result = self._compile(project, iteration + 1, state)
                if not result.success and good:
                    result = self._undo_last_repairs(project, *good, state, iteration + 1)
        return result, state, iteration

    def _undo_last_repairs(self, project: LaTeXProject, tex: str, good_state: qa_repair.RepairState,
                           state: qa_repair.RepairState, iteration: int) -> CompileResult:
        """A repair stopped a paper that compiled from compiling: go back to the last version that made a PDF."""
        self.ctx.log("QA & Repair", "The last repair stopped the paper from compiling, so it was undone.", "warning")
        Path(project.root_dir, project.main_file).write_text(tex, encoding="utf-8")
        vars(state).update(vars(good_state), allow_network=state.allow_network)
        self._step("Compiler (final pass)")
        return self._compile(project, iteration + 1, state)

    def _compile(self, project: LaTeXProject, iteration: int, state: qa_repair.RepairState) -> CompileResult:
        result = compiler_agent.run(self.ctx, project, iteration, allow_network=state.allow_network)
        # Once Tectonic needed to download packages, later passes may download too.
        state.allow_network = state.allow_network or self.ctx.data.get("allow_network", False)
        return result

    def _save_outputs(self, result: CompileResult, report: ComplianceReport, paths: dict) -> None:
        ctx = self.ctx
        final = ctx.workspace.final
        pdf_out = None
        if result.success and result.pdf_path:
            pdf_out = final / "paper.pdf"
            shutil.copyfile(result.pdf_path, pdf_out)
        zip_out = zip_latex_project(ctx.workspace.work, final / "latex_source.zip")
        output = FinalOutput(job_id=ctx.job_id, pdf_path=str(pdf_out) if pdf_out else None, zip_path=str(zip_out),
                             report_json_path=str(paths["json"]), report_html_path=str(paths["html"]),
                             report_md_path=str(paths["md"]), overall_status=report.overall_status)
        self.store.set_outputs(output)
        if pdf_out:
            self.store.update(ctx.job_id, status=JobStatus.completed, current_step="Done",
                              overall_status=report.overall_status)
            ctx.log("Orchestrator", "Finished. The PDF, LaTeX source and report are ready to download.", "success")
        else:
            self.store.update(ctx.job_id, status=JobStatus.failed, current_step="Done",
                              overall_status=report.overall_status,
                              error="LaTeX could not be compiled to PDF. The LaTeX source and the report explain why.")
            ctx.log("Orchestrator", "No PDF could be produced. The LaTeX source ZIP and report are available.", "error")
