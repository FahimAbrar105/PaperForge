"""Parse TeX / Tectonic / BibTeX output into structured LogIssue records."""

from __future__ import annotations

import re

from app.models.compile import LogIssue

RE_ERROR = re.compile(r"^! (.*)$")
RE_FLE_LOG = re.compile(r"^(?:\./)?([^\s:]+\.(?:tex|bbl|sty|cls|aux)):(\d+): (.*)$")
RE_FILE_LINE_ERROR = re.compile(r"^(?:error|warning): (?:([^:\s]+\.tex):(\d+): )?(.*)$")
RE_LINE_NO = re.compile(r"^l\.(\d+)\s?(.*)$")
RE_CITATION = re.compile(r"Citation [`'\"]([^'`\"]+)['`\"](?: on page \d+)? undefined(?: on input line (\d+))?")
RE_REFERENCE = re.compile(r"Reference [`'\"]([^'`\"]+)['`\"](?: on page \d+)? undefined(?: on input line (\d+))?")
RE_OVERFULL = re.compile(r"Overfull \\([hv])box \(([\d.]+)pt too (?:wide|high)\)(?: (?:in paragraph|detected) at lines? (\d+)(?:--(\d+))?)?")
RE_UNDERFULL = re.compile(r"Underfull \\([hv])box \(badness (\d+)\)(?: (?:in paragraph|detected) at lines? (\d+))?")
RE_FILE_NOT_FOUND = re.compile(r"File [`'\"]([^'`\"]+)['`\"] not found")
RE_PICTURE = re.compile(r"Unable to load picture or PDF file ['`\"]([^'`\"]+)['`\"]")
RE_MISSING_CHAR = re.compile(r"Missing character: There is no (.+?) (?:\(U\+([0-9A-F]+)\) )?in font")
RE_BIB_MISSING = re.compile(r"Warning--I didn't find a database entry for [\"']([^\"']+)[\"']")
RE_BIB_DB = re.compile(r"I couldn't open (?:database|style) file (\S+)")
RE_ALREADY_DEFINED = re.compile(r"Command (\\[A-Za-z@]+) already defined")
RE_UNDEFINED_CS = re.compile(r"Undefined control sequence")
RE_ENV_UNDEFINED = re.compile(r"Environment (\S+) undefined")
RE_UNICODE = re.compile(r"Unicode character (.) \(U\+([0-9A-F]+)\)")
RE_TECTONIC_NOT_CACHED = re.compile(r"(not (?:present )?in (?:the )?(?:local )?cache|only-cached|unable to fetch|error sending request|failed to (?:download|connect))", re.I)


def parse_log(log_text: str, stderr: str = "") -> list[LogIssue]:
    issues: list[LogIssue] = []
    seen: set[tuple] = set()

    def add(issue: LogIssue) -> None:
        key = (issue.kind, issue.target, issue.line)
        if key not in seen:
            seen.add(key)
            issues.append(issue)

    lines = log_text.splitlines()
    for i, line in enumerate(lines):
        error = RE_ERROR.match(line)
        file_line_error = RE_FLE_LOG.match(line)
        if error:
            lineno, context = _source_line(lines, i)
            add(_issue_from_error(error.group(1).strip(), lineno, context))
        elif file_line_error and "==> Fatal error occurred" not in line and "Emergency stop" not in line:
            _, context = _source_line(lines, i)
            add(_issue_from_error(file_line_error.group(3).strip(), int(file_line_error.group(2)), context,
                                  file=file_line_error.group(1)))
        else:
            warning = _warning(line)
            if warning:
                add(warning)

    # Tectonic reports some errors only on stderr. Its warnings there can come from
    # intermediate passes, so only errors are read; the final log is authoritative.
    for line in stderr.splitlines():
        line = line.strip()
        m = RE_FILE_LINE_ERROR.match(line)
        if not m or not line.startswith("error"):
            continue
        msg = m.group(3).strip()
        if RE_TECTONIC_NOT_CACHED.search(msg):
            add(LogIssue(kind="missing_package", severity="error", message=msg, target="__network__"))
        elif not msg.startswith(("halted on", "the TeX engine had an error", "something bad happened")):
            add(_issue_from_error(msg, int(m.group(2)) if m.group(2) else None, "", file=m.group(1)))
    return issues


def _source_line(lines: list[str], i: int) -> tuple[int | None, str]:
    """TeX prints 'l.<line> <text>' a few lines after an error: return that line number and text."""
    for following in lines[i + 1 : i + 8]:
        m = RE_LINE_NO.match(following)
        if m:
            return int(m.group(1)), m.group(2).strip()
    return None, ""


def _issue_from_error(msg: str, lineno: int | None, context: str, file: str | None = None) -> LogIssue:
    message = re.sub(r"^LaTeX Error:\s*", "", msg)
    kind, target = "fatal_error", None
    if m := RE_FILE_NOT_FOUND.search(msg) or RE_PICTURE.search(msg):
        target = m.group(1)
        kind = "missing_package" if target.lower().endswith((".sty", ".cls")) else "missing_file"
    elif m := RE_UNICODE.search(msg):
        kind, target = "unicode_error", m.group(1)
    elif m := RE_ALREADY_DEFINED.search(msg) or RE_ENV_UNDEFINED.search(msg):
        target = m.group(1)
    elif RE_UNDEFINED_CS.search(msg):
        message = "Undefined control sequence"
        cs = re.search(r"(\\[A-Za-z@]+)\s*$", context)
        target = cs.group(1) if cs else None
    return LogIssue(kind=kind, severity="error", message=message, line=lineno, target=target, context=context, file=file)


def _line_number(m: re.Match, group: int) -> int | None:
    return int(m.group(group)) if m.group(group) else None


def _warning(line: str) -> LogIssue | None:
    if m := RE_CITATION.search(line):
        return LogIssue(kind="undefined_citation", severity="warning", message=f"Citation '{m.group(1)}' undefined",
                        target=m.group(1), line=_line_number(m, 2))
    if m := RE_REFERENCE.search(line):
        return LogIssue(kind="undefined_reference", severity="warning", message=f"Reference '{m.group(1)}' undefined",
                        target=m.group(1), line=_line_number(m, 2))
    if m := RE_OVERFULL.search(line):
        return LogIssue(kind="overfull_hbox", severity="warning", message=m.group(0), amount_pt=float(m.group(2)),
                        line=_line_number(m, 3))
    if m := RE_UNDERFULL.search(line):
        return LogIssue(kind="underfull_hbox", severity="info", message=m.group(0), line=_line_number(m, 3))
    if m := RE_MISSING_CHAR.search(line):
        return LogIssue(kind="font_warning", severity="warning", message=f"Missing glyph for '{m.group(1)}' in the font",
                        target=m.group(1))
    if m := RE_BIB_MISSING.search(line):
        return LogIssue(kind="undefined_citation", severity="warning", message=f"No bibliography entry for '{m.group(1)}'",
                        target=m.group(1))
    if m := RE_BIB_DB.search(line):
        return LogIssue(kind="bibtex_error", severity="error", message=m.group(0), target=m.group(1))
    return None


def summarize(issues: list[LogIssue]) -> str:
    counts: dict[str, int] = {}
    for i in issues:
        counts[i.kind] = counts.get(i.kind, 0) + 1
    return ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in sorted(counts.items())) or "no issues"
