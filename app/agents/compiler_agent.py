"""Step 5 - Compiler Service: run Tectonic and return a structured CompileResult."""

from __future__ import annotations

import re
from pathlib import Path

from app.agents.base import JobCancelled, StepContext, StepError
from app.compilers.log_parser import summarize
from app.compilers.tectonic import CompilerNotFound, run_compile
from app.models.compile import CompileResult
from app.models.latex import LaTeXProject

STEP = "Compiler"
NO_INTERNET = re.compile(r"error sending request|unable to fetch|failed to (?:download|connect)|dns error|"
                         r"could not resolve|network is unreachable|connection refused", re.I)


def run(ctx: StepContext, project: LaTeXProject, iteration: int, allow_network: bool) -> CompileResult:
    ctx.check_cancelled()
    work = Path(project.root_dir)

    def compile_once(only_cached: bool) -> CompileResult:
        return run_compile(work, iteration, ctx.settings.tectonic_path, ctx.settings.project_root,
                           timeout_s=ctx.settings.compile_timeout_s, cancel_event=ctx.cancel_event,
                           only_cached=only_cached, main_file=project.main_file)

    try:
        result = compile_once(only_cached=not allow_network)
        # Offline, Tectonic stops at the first package, font or style file it has not cached yet, and the error
        # can look like any LaTeX error. So a failed offline compile is retried once with downloads allowed.
        if (not result.success and not allow_network and not result.cancelled and not ctx.data.get("offline")
                and result.command and result.command[0].startswith("tectonic")):
            ctx.log(STEP, "Compiling with the LaTeX packages on this computer failed; retrying with downloads "
                          "allowed, in case a package, font or style file is not downloaded yet.")
            retry = compile_once(only_cached=False)
            if retry.cancelled or not NO_INTERNET.search(retry.stderr_tail):
                result = retry
                ctx.data["allow_network"] = True
            else:
                ctx.data["offline"] = True
                ctx.log(STEP, "Tectonic could not reach its package server (no internet?); continuing with the "
                              "packages on this computer.", "warning")
    except CompilerNotFound as exc:
        raise StepError(str(exc)) from exc
    if result.cancelled:
        raise JobCancelled()
    level = "success" if result.success else "error"
    ctx.log(STEP, f"Pass {iteration}: {'PDF created' if result.success else 'failed'} in {result.duration_seconds:.1f}s"
                  + (f", {result.page_count} page(s)" if result.page_count else "")
                  + f" ({summarize(result.issues)})", level)
    (ctx.workspace.logs / f"compile_{iteration}.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return result
