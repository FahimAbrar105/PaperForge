"""Run Tectonic (or latexmk as a developer fallback) and collect a CompileResult."""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

from app.compilers.log_parser import parse_log
from app.models.compile import CompileResult, LogIssue


class CompilerNotFound(RuntimeError):
    pass


def tectonic_cache_dir(project_root: Path) -> Path:
    env = os.environ.get("TECTONIC_CACHE_DIR")
    if env:
        return Path(env)
    return project_root / "runtime" / "tectonic-cache"


def find_engine(tectonic_path: str | None) -> tuple[str, str]:
    """Return (engine_name, executable)."""
    if tectonic_path and (Path(tectonic_path).is_file() or shutil.which(tectonic_path)):
        return "tectonic", tectonic_path
    latexmk = shutil.which("latexmk")
    if latexmk and os.environ.get("PAPERFORGE_ALLOW_LATEXMK", "1") == "1":
        return "latexmk", latexmk
    raise CompilerNotFound(
        "Tectonic was not found. On Windows run run.bat once with internet access so it can download "
        "Tectonic into runtime\\tectonic; with Docker, rebuild the image."
    )


def _tail(text: str, n: int = 4000) -> str:
    return text[-n:]


def run_compile(
    work_dir: Path,
    iteration: int,
    tectonic_path: str | None,
    project_root: Path,
    timeout_s: int = 180,
    cancel_event: threading.Event | None = None,
    only_cached: bool = True,
    main_file: str = "main.tex",
) -> CompileResult:
    engine, exe = find_engine(tectonic_path)
    build_dir = work_dir / "build"
    if build_dir.exists():
        shutil.rmtree(build_dir, ignore_errors=True)
    build_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    if engine == "tectonic":
        cmd = [exe, "-X", "compile", main_file, "--keep-logs", "--keep-intermediates",
               "--outdir", "build", "--untrusted"]
        if only_cached:
            cmd.append("--only-cached")
        cache = tectonic_cache_dir(project_root)
        cache.mkdir(parents=True, exist_ok=True)
        env["TECTONIC_CACHE_DIR"] = str(cache)
    else:
        cmd = [exe, "-pdf", "-interaction=nonstopmode", "-halt-on-error", "-file-line-error",
               "-outdir=build", "-no-shell-escape", main_file]

    started = time.monotonic()
    timed_out = cancelled = False
    proc = subprocess.Popen(
        cmd, cwd=str(work_dir), stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
        env=env, text=True, encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    out_chunks: list[str] = []
    err_chunks: list[str] = []

    def pump(stream, sink):
        for line in iter(stream.readline, ""):
            sink.append(line)
        stream.close()

    t_out = threading.Thread(target=pump, args=(proc.stdout, out_chunks), daemon=True)
    t_err = threading.Thread(target=pump, args=(proc.stderr, err_chunks), daemon=True)
    t_out.start()
    t_err.start()
    while proc.poll() is None:
        if cancel_event is not None and cancel_event.is_set():
            cancelled = True
            proc.kill()
            break
        if time.monotonic() - started > timeout_s:
            timed_out = True
            proc.kill()
            break
        time.sleep(0.2)
    proc.wait()
    t_out.join(timeout=5)
    t_err.join(timeout=5)
    duration = time.monotonic() - started
    stdout, stderr = "".join(out_chunks), "".join(err_chunks)

    stem = Path(main_file).stem
    log_path = build_dir / f"{stem}.log"
    log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    blg = build_dir / f"{stem}.blg"
    if blg.exists():
        log_text += "\n" + blg.read_text(encoding="utf-8", errors="replace")
    # Only the final pass's log is trusted for warnings; earlier passes always have undefined references.
    issues = parse_log(log_text, stderr if engine == "tectonic" else "")
    if timed_out:
        issues.insert(0, LogIssue(kind="fatal_error", severity="error",
                                  message=f"Compilation timed out after {timeout_s} seconds."))
    pdf = build_dir / f"{stem}.pdf"
    success = proc.returncode == 0 and pdf.exists() and not timed_out and not cancelled
    if not success and not timed_out and not cancelled and not any(i.severity == "error" for i in issues):
        issues.append(LogIssue(kind="fatal_error", severity="error",
                               message=(_tail(stderr, 600) or "Compiler failed without a readable error.").strip()))
    page_count = None
    if pdf.exists():
        try:
            import pymupdf as fitz

            with fitz.open(str(pdf)) as d:
                page_count = d.page_count
        except Exception:
            page_count = None
    return CompileResult(
        iteration=max(1, min(iteration, 5)),
        success=success,
        exit_code=proc.returncode,
        timed_out=timed_out,
        cancelled=cancelled,
        duration_seconds=round(duration, 2),
        command=[Path(cmd[0]).name, *cmd[1:]],
        pdf_path=str(pdf) if pdf.exists() else None,
        page_count=page_count,
        log_path=str(log_path) if log_path.exists() else None,
        stdout_tail=_tail(stdout),
        stderr_tail=_tail(stderr),
        issues=issues,
    )
