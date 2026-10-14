"""Step 6 - QA and Repair Agent.

Reads the compile result and repairs the generated LaTeX. The orchestrator
repeats compile -> repair up to the configured number of passes.

- Full agentic mode: on every pass with problems, an AI agent reads the errors
  and an excerpt of main.tex and chooses repair tools (add or remove a package,
  placeholder for a missing figure, small line patch, ...). Each tool call is
  validated before it is applied. If the agent has no usable answer, or the AI
  limit is reached, the rule-based repairs below run instead.
- Partial mode: rules first; the AI only suggests a patch for an error no rule
  understands.
- Off: rules only.

A patch is accepted only if it is small and keeps the author's words.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from app.agents.base import StepContext
from app.agents.latex_formatter import THEOREM_ENVS
from app.formatters.figures import placeholder, prepare_figure, resolve_figure
from app.models.compile import CompileResult, LogIssue
from app.models.latex import LaTeXProject
from app.models.qa import RepairAction
from app.models.venue import VenueSpec
from app.parsers.text_utils import unicode_to_latex

STEP = "QA & Repair"

# Commands commonly used without loading their package.
COMMAND_PACKAGES = {
    "\\toprule": "booktabs", "\\midrule": "booktabs", "\\bottomrule": "booktabs", "\\cmidrule": "booktabs",
    "\\multirow": "multirow", "\\SI": "siunitx", "\\si": "siunitx", "\\num": "siunitx", "\\bm": "bm",
    "\\mathbb": "amssymb", "\\checkmark": "amssymb", "\\href": "hyperref", "\\xspace": "xspace",
    "\\sout": "ulem", "\\hl": "soul", "\\subfloat": "subfig", "\\coloneqq": "mathtools",
    "\\makecell": "makecell", "\\lipsum": "lipsum", "\\resizebox": "graphicx", "\\textcolor": "xcolor",
    "\\algorithmicrequire": "algorithmic", "\\State": "algpseudocode", "\\nicefrac": "nicefrac",
    "\\tnote": "threeparttable", "\\rowcolor": "colortbl", "\\cellcolor": "colortbl",
}
# Commands to rewrite when their package is unavailable or not allowed.
COMMAND_REWRITES = {
    "\\cref": "\\ref", "\\Cref": "\\ref", "\\autoref": "\\ref", "\\nameref": "\\ref",
    "\\degree": "\\textdegree", "\\includesvg": "\\includegraphics",
}
ENV_PACKAGES = {
    "algorithm": "algorithm", "lstlisting": "listings", "tabularx": "tabularx", "subfigure": "subcaption",
    "longtable": "longtable", "threeparttable": "threeparttable", "algorithmic": "algorithmic",
    "multicols": "multicol", "tikzpicture": "tikz", "comment": "verbatim", "proof": "amsthm",
}
ESSENTIAL_PACKAGES = {"graphicx", "amsmath", "cite", "IEEEtran"}
# Commands the repair agent may never rewrite.
PROTECTED_COMMANDS = {"\\begin", "\\end", "\\section", "\\cite", "\\documentclass", "\\input", "\\item"}
PACKAGE_NAME = re.compile(r"[A-Za-z][A-Za-z0-9\-]*")
COMMAND_NAME = re.compile(r"\\[A-Za-z]+")
# The space before a citation is removed with it, so no "text ." is left behind.
CITE_RE = re.compile(r"(?P<space>[ \t]*)(?P<cmd>~?\\cite[a-zA-Z]*\*?(?:\[[^\]]*\])?)\{(?P<keys>[^}]*)\}")

AI_REPAIR_SYSTEM = (
    "You fix LaTeX compile errors with the smallest possible edit. Never delete or rewrite the author's "
    "sentences, results, citations or equations' meaning. Return only JSON."
)
AI_REPAIR_PROMPT = """The LaTeX file below fails to compile.
Error: {error}
Line {line} (numbered excerpt, lines {start}-{end}):
{excerpt}

Return JSON: {{"line_start": <int>, "line_end": <int>, "replacement": "<new text for those lines>",
"explanation": "<one sentence>"}}. line_start/line_end are inclusive line numbers from the excerpt.
If you are not confident, return {{"line_start": 0, "line_end": 0, "replacement": "", "explanation": "unsure"}}."""

AGENT_SYSTEM = (
    "You are the QA & Repair agent of a LaTeX formatting pipeline. You pick the smallest set of tool actions "
    "that fix compile problems. Never delete or reword the author's sentences, results, citations or the meaning "
    "of equations. Return only JSON."
)
AGENT_PROMPT = """Compile pass {iteration} of main.tex for {venue} ({status}).
Problems found in the compile log:
{issues}
{excerpt}
Figure files referenced but not uploaded: {missing}
Citation keys with a bibliography entry: {bib_keys}

Tools (use any number, in order):
- {{"tool": "allow_downloads"}}: let the compiler download a LaTeX package that is not cached yet
- {{"tool": "add_package", "name": "<package>"}}
- {{"tool": "remove_package", "name": "<package>"}}
- {{"tool": "placeholder_figure", "file": "<file name>"}}: use an uploaded file with that name, or a labelled box
- {{"tool": "remove_citation", "key": "<key>"}}: only for a key with no bibliography entry
- {{"tool": "replace_command", "old": "\\cmd", "new": "\\othercmd"}}
- {{"tool": "define_theorem", "name": "<environment>", "title": "<Printed name>"}}
- {{"tool": "scale_table", "line": <line number of an overfull box inside a tabular>}}
- {{"tool": "sloppy"}}: relax line breaking to remove overfull lines
- {{"tool": "patch_lines", "line_start": <int>, "line_end": <int>, "replacement": "<new text>"}}: edit at most 6
  lines shown in the excerpt
Return {{"actions": [...], "explanation": "<one sentence>"}}. Return {{"actions": []}} when nothing should change.
Give one placeholder_figure action per missing figure."""


@dataclass
class RepairState:
    applied: set[str] = field(default_factory=set)  # signatures of repairs already made, so none repeats
    actions: list[RepairAction] = field(default_factory=list)
    removed_citations: list[str] = field(default_factory=list)
    placeholder_figures: list[str] = field(default_factory=list)
    removed_packages: set[str] = field(default_factory=set)
    allow_network: bool = False
    sloppy: bool = False
    ai_repairs: int = 0


class Repairer:
    def __init__(self, ctx: StepContext, project: LaTeXProject, spec: VenueSpec, state: RepairState) -> None:
        self.ctx = ctx
        self.project = project
        self.spec = spec
        self.state = state
        self.main_path = Path(project.root_dir) / project.main_file
        self.tex = self.main_path.read_text(encoding="utf-8")
        self.iteration = 0
        self.source = "deterministic"  # who is making the current repairs

    # ------------------------------------------------------------- entry
    def repair(self, result: CompileResult, iteration: int) -> bool:
        """Apply repairs for this compile result. Returns True if main.tex changed."""
        self.iteration = iteration
        self.tex = self.main_path.read_text(encoding="utf-8")
        ai = self.ctx.ai
        step = f"{STEP} (pass {iteration})"
        if ai is not None and ai.full:
            problems = self._problems(result)
            if problems and self._repair_with_agent(result, problems, step):
                return True
            # Mechanical fixes, such as characters the font cannot print, need no agent; rules always make them.
            changed = self._repair_with_rules(result)
            if not problems:
                ai.record(step, "rules", "Only mechanical fixes were needed (for example special characters)."
                          if changed else "Nothing needed fixing.")
            return changed
        if ai is not None:
            ai.record(step, "rules", "Rule-based repairs.")
        return self._repair_with_rules(result)

    def _repair_with_agent(self, result: CompileResult, problems: list[LogIssue], step: str) -> bool:
        ai = self.ctx.ai
        before = self.tex
        changed, provider, proposed = self.try_agent(result, problems) if ai.can_ask else (False, None, 0)
        if changed:
            ai.record(step, "ai", f"Chose and applied repairs for {len(problems)} problem(s).", provider)
            self.main_path.write_text(self.tex, encoding="utf-8")
            return True
        if provider is None:
            ai.fallback(step)
        elif proposed:
            ai.reject(step, provider, "none of its repairs could be applied")
        else:
            ai.record(step, "rules", "The agent proposed no repair; the rule-based repairs were tried.", provider)
        self.tex = before
        return False

    def _repair_with_rules(self, result: CompileResult) -> bool:
        before = self.tex
        changed = False
        unresolved_fatal: list[LogIssue] = []
        for issue in result.issues:
            fixed = self._fix_issue(issue)
            if issue.kind == "fatal_error" and not fixed:
                unresolved_fatal.append(issue)
            changed = fixed or changed
        if any(i.kind == "missing_file" for i in result.issues):
            # LaTeX stops at the first missing figure; fix every figure the formatter could not find in one pass.
            for ref in list(self.project.missing_figures):
                changed = self.fix_missing_file(Path(ref).name) or changed
        if result.success and not changed:
            changed = self.fix_overfull(result.issues)
        if not result.success and not changed and unresolved_fatal:
            changed = self.try_ai(unresolved_fatal[0])
        if self.tex != before:
            self.main_path.write_text(self.tex, encoding="utf-8")
        return changed

    def _fix_issue(self, issue: LogIssue) -> bool:
        if issue.kind == "missing_file":
            return self.fix_missing_file(issue.target or "")
        if issue.kind == "missing_package":
            return self.fix_missing_package(issue)
        if issue.kind == "undefined_citation":
            return self.remove_citation(issue.target or "")
        if issue.kind in {"unicode_error", "font_warning"}:
            return self.fix_unicode(issue)
        if issue.kind == "fatal_error":
            return self.fix_fatal(issue) or self.fix_empty_bibliography(issue)
        return False

    # ------------------------------------------------------------- helpers
    def _record(self, signature: str, kind: str, action: str, source: str | None = None) -> None:
        self.state.applied.add(signature)
        self.state.actions.append(RepairAction(iteration=self.iteration, issue_kind=kind, action=action,
                                               file=self.project.main_file, source=source or self.source))
        self.ctx.log(STEP, f"Repair: {action}", "info")

    def _insert_before_document(self, text: str) -> None:
        self.tex = self.tex.replace("\\begin{document}", text + "\\begin{document}", 1)

    def _add_package(self, pkg: str) -> bool:
        if pkg in self.state.removed_packages:
            return False  # removed earlier because it is not available; adding it back would loop
        if re.search(r"\\usepackage(\[[^\]]*\])?\{[^}]*\b" + re.escape(pkg) + r"\b[^}]*\}", self.tex):
            return False
        self._insert_before_document(f"\\usepackage{{{pkg}}}\n")
        return True

    def _remove_package(self, pkg: str) -> bool:
        changed = False

        def drop(m: re.Match) -> str:
            nonlocal changed
            names = [n.strip() for n in m.group(2).split(",")]
            if pkg not in names:
                return m.group(0)
            changed = True
            names.remove(pkg)
            return f"\\usepackage{m.group(1) or ''}{{{','.join(names)}}}" if names else ""

        self.tex = re.sub(r"\\usepackage(\[[^\]]*\])?\{([^}]+)\}", drop, self.tex)
        return changed

    def _drop_package(self, pkg: str, kind: str, action: str) -> bool:
        sig = f"missing_package:{pkg}"
        if sig in self.state.applied or not self._remove_package(pkg):
            return False
        self.state.removed_packages.add(pkg)
        self._record(sig, kind, action)
        return True

    def _allow_downloads(self, kind: str, action: str) -> bool:
        if self.state.allow_network or self.ctx.data.get("offline"):
            return False
        self.state.allow_network = True
        self._record("network", kind, action)
        return True

    def _replace_command(self, old: str, new: str) -> None:
        self.tex = re.sub(re.escape(old) + r"(?![A-Za-z])", lambda _m: new, self.tex)

    def _define_theorem(self, env: str, title: str) -> bool:
        if f"\\newtheorem{{{env}}}" in self.tex:
            return False
        self._add_package("amsthm")
        self._insert_before_document(f"\\newtheorem{{{env}}}{{{title}}}\n")
        self._record(f"env:{env}", "fatal_error", f"Defined the '{env}' environment (amsthm)")
        return True

    def _bib_keys(self) -> set[str]:
        keys: set[str] = set()
        if self.project.bib_file:
            bib = Path(self.project.root_dir) / self.project.bib_file
            if bib.exists():
                keys |= set(re.findall(r"@\w+\s*\{\s*([^,\s]+)\s*,", bib.read_text(encoding="utf-8", errors="replace")))
        keys |= set(re.findall(r"\\bibitem(?:\[[^\]]*\])?\{([^}]+)\}", self.tex))
        return keys

    def _overfull_threshold(self) -> float:
        for check in self.spec.checks:
            if check.type == "overfull_boxes":
                return float(check.params.get("threshold_pt", 5))
        return 5.0

    def _excerpt(self, line: int) -> tuple[int, int, str]:
        """Numbered lines of main.tex around ``line``: (first line, last line, text)."""
        lines = self.tex.split("\n")
        if not 1 <= line <= len(lines):
            return 0, 0, ""
        start, end = max(1, line - 12), min(len(lines), line + 12)
        return start, end, "\n".join(f"{n}: {lines[n - 1]}" for n in range(start, end + 1))

    # ------------------------------------------------------------- rule-based repairs
    def fix_missing_file(self, target: str) -> bool:
        name = Path(target).name
        sig = f"missing_file:{name}"
        if not name or sig in self.state.applied:
            return False
        graphic = re.compile(r"(\\includegraphics\*?(?:\[[^\]]*\])?\{)" + re.escape(target) + r"\}")
        src = resolve_figure(name, Path(self.ctx.workspace.uploads))
        if src is not None:
            latex_name, problem = prepare_figure(src, Path(self.project.root_dir) / "figures")
            if latex_name and not problem and graphic.search(self.tex):
                self.tex = graphic.sub(lambda m: m.group(1) + latex_name + "}", self.tex)
                self._record(sig, "missing_file", f"Pointed \\includegraphics{{{target}}} to uploaded file {latex_name}")
                return True
        if graphic.search(self.tex):
            box = placeholder(name)
            self.tex = graphic.sub(lambda _m: box, self.tex)
            self.state.placeholder_figures.append(name)
            if name not in self.project.missing_figures:
                self.project.missing_figures.append(name)
            self._record(sig, "missing_file", f"Figure file '{name}' not uploaded: inserted a placeholder box")
            return True
        include = re.compile(r"\\(input|include)\{" + re.escape(Path(target).stem) + r"(\.tex)?\}")
        if target.endswith(".tex") and include.search(self.tex):
            self.tex = include.sub("", self.tex)
            self._record(sig, "missing_file", f"Removed \\input of missing file '{target}' (content was not uploaded)")
            return True
        return False

    def fix_missing_package(self, issue: LogIssue) -> bool:
        if issue.target == "__network__":
            return self._allow_downloads(issue.kind, "A LaTeX package is not in the offline cache: allowing Tectonic "
                                                     "to download it")
        pkg = Path(issue.target or "").stem
        if not pkg or f"missing_package:{pkg}" in self.state.applied or pkg in ESSENTIAL_PACKAGES:
            return False
        # Tectonic may simply not have this package cached yet: try downloading first, then remove it.
        return (self._allow_downloads(issue.kind, f"Package '{pkg}' not cached: allowing Tectonic to download it")
                or self._drop_package(pkg, issue.kind, f"Removed \\usepackage{{{pkg}}}: package is not available"))

    def remove_citation(self, key: str) -> bool:
        """Remove a \\cite key that has no bibliography entry."""
        sig = f"cite:{key}"
        if not key or sig in self.state.applied or key in self._bib_keys():
            # An existing entry means the warning comes from an incomplete BibTeX pass, not from missing data.
            return False

        def drop_key(m: re.Match) -> str:
            keys = [k.strip() for k in m["keys"].split(",")]
            if key not in keys:
                return m.group(0)
            remaining = [k for k in keys if k != key]
            return f"{m['space']}{m['cmd']}{{{','.join(remaining)}}}" if remaining else ""

        new_tex = CITE_RE.sub(drop_key, self.tex)
        if new_tex == self.tex:
            return False
        self.tex = new_tex
        self.state.removed_citations.append(key)
        self._record(sig, "undefined_citation", f"Removed citation '{key}': it has no bibliography entry (flagged in report)")
        return True

    def fix_empty_bibliography(self, issue: LogIssue) -> bool:
        """BibTeX writes an empty list when nothing is cited, which LaTeX rejects ('missing \\item')."""
        if "missing \\item" not in issue.message or "empty_bib" in self.state.applied:
            return False
        if re.search(r"\\cite[a-zA-Z]*\*?(\[[^\]]*\])?\{", self.tex):
            return False
        new_tex = re.sub(r"\\bibliographystyle\{[^}]*\}\s*|\\bibliography\{[^}]*\}\s*", "", self.tex)
        if new_tex == self.tex:
            return False
        self.tex = new_tex
        self._record("empty_bib", issue.kind, "Removed the empty bibliography: the paper cites nothing (flagged in report)")
        return True

    def fix_unicode(self, issue: LogIssue) -> bool:
        ch = (issue.target or "")[:1]
        sig = f"unicode:{ord(ch)}" if ch else ""
        if not ch or sig in self.state.applied or ch not in self.tex:
            return False
        replacement = unicode_to_latex(ch)
        if replacement == ch:
            return False
        self.tex = self.tex.replace(ch, replacement)
        self._record(sig, issue.kind, f"Replaced character U+{ord(ch):04X} with {replacement or '(nothing)'}")
        # LaTeX reports one bad character per run: replace every other known one now to save compile passes.
        others = sorted({c for c in self.tex if ord(c) > 127 and unicode_to_latex(c) != c})
        if others:
            for c in others:
                self.tex = self.tex.replace(c, unicode_to_latex(c))
                self.state.applied.add(f"unicode:{ord(c)}")
            self._record("unicode_sweep:" + "".join(others), issue.kind,
                         f"Also replaced {len(others)} other special character(s): {' '.join(others)[:80]}")
        return True

    def fix_fatal(self, issue: LogIssue) -> bool:
        if m := re.search(r"Command (\\[A-Za-z@]+) already defined", issue.message):
            return self._fix_already_defined(m.group(1))
        if "Undefined control sequence" in issue.message and issue.target:
            return self._fix_undefined_command(issue.target)
        if m := re.search(r"Environment (\S+) undefined", issue.message):
            return self._fix_undefined_environment(m.group(1))
        if m := re.search(r"Option clash for package ([\w-]+)", issue.message):
            return self._drop_package(m.group(1), "fatal_error", f"Removed \\usepackage{{{m.group(1)}}}: the venue's "
                                                                 "style loads it with its own options")
        return False

    def _fix_already_defined(self, cmd: str) -> bool:
        sig = f"redefine:{cmd}"
        if sig in self.state.applied:
            return False
        newcommand = re.compile(r"\\newcommand\*?\s*(\{\s*" + re.escape(cmd) + r"\s*\}|" + re.escape(cmd) + r"(?![A-Za-z]))")
        if newcommand.search(self.tex):
            self.tex = newcommand.sub(lambda m: "\\renewcommand" + m.group(1), self.tex, count=1)
            self._record(sig, "fatal_error", f"Changed \\newcommand{cmd} to \\renewcommand (already defined by the template)")
            return True
        operator = re.compile(r"\\DeclareMathOperator\*?\s*\{\s*" + re.escape(cmd) + r"\s*\}\s*\{[^}]*\}")
        if operator.search(self.tex):
            self.tex = operator.sub("", self.tex, count=1)
            self._record(sig, "fatal_error", f"Removed duplicate \\DeclareMathOperator{cmd}")
            return True
        return False

    def _fix_undefined_command(self, cmd: str) -> bool:
        sig = f"undefined_cs:{cmd}"
        if sig in self.state.applied:
            return False
        package = COMMAND_PACKAGES.get(cmd)
        if package in self.state.removed_packages:
            self.ctx.log(STEP, f"{cmd} needs the '{package}' package, which is not available. Replace {cmd} in your source.",
                         "warning")
        elif package and self._add_package(package):
            self._record(sig, "fatal_error", f"Added \\usepackage{{{package}}} for {cmd}")
            return True
        if cmd in COMMAND_REWRITES:
            self._replace_command(cmd, COMMAND_REWRITES[cmd])
            self._record(sig, "fatal_error", f"Replaced {cmd} with {COMMAND_REWRITES[cmd]}")
            return True
        return False

    def _fix_undefined_environment(self, env: str) -> bool:
        if f"env:{env}" in self.state.applied:
            return False
        if env in THEOREM_ENVS:
            return self._define_theorem(env, THEOREM_ENVS[env])
        package = ENV_PACKAGES.get(env)
        if package and self._add_package(package):
            self._record(f"env:{env}", "fatal_error", f"Added \\usepackage{{{package}}} for environment '{env}'")
            return True
        return False

    def fix_overfull(self, issues: list[LogIssue]) -> bool:
        threshold = self._overfull_threshold()
        big = [i for i in issues if i.kind == "overfull_hbox" and (i.amount_pt or 0) > threshold]
        if not big:
            return False
        # Wide tables: shrink the tabular that contains the offending line. Otherwise relax line breaking.
        scaled = [self.scale_table_at(issue.line or 0) for issue in big]
        return any(scaled) or self.make_sloppy()

    def scale_table_at(self, line_no: int) -> bool:
        lines = self.tex.split("\n")
        if not 1 <= line_no <= len(lines):
            return False
        idx = line_no - 1
        start = next((j for j in range(idx, max(-1, idx - 60), -1) if "\\begin{tabular" in lines[j]), None)
        end = next((j for j in range(idx, min(len(lines), idx + 200)) if "\\end{tabular" in lines[j]), None)
        sig = f"resize:{start}"
        if start is None or end is None or sig in self.state.applied or "\\resizebox" in lines[start]:
            return False
        in_wide_table = any("\\begin{table*}" in line for line in lines[max(0, start - 8):start])
        width = "\\textwidth" if in_wide_table else "\\columnwidth"
        # The box goes on the tabular's own lines, so the line numbers of the other overfull boxes stay right.
        lines[start] = re.sub(r"\\begin\{tabular[x*]?\}", lambda m: f"\\resizebox{{{width}}}{{!}}{{" + m.group(0),
                              lines[start], count=1)
        lines[end] = re.sub(r"\\end\{tabular[x*]?\}", lambda m: m.group(0) + "}", lines[end], count=1)
        self.tex = "\n".join(lines)
        self._record(sig, "overfull_hbox", f"Scaled a wide table (line {start + 1}) to fit the column")
        return True

    def make_sloppy(self) -> bool:
        if self.state.sloppy:
            return False
        self.state.sloppy = True
        self.tex = self.tex.replace("\\begin{document}", "\\begin{document}\n\\sloppy", 1)
        self._record("sloppy", "overfull_hbox", "Enabled \\sloppy line breaking to keep text inside the margins")
        return True

    # ------------------------------------------------------------- AI patch (Partial mode)
    def try_ai(self, issue: LogIssue) -> bool:
        """Ask the AI for a small line patch for an error no rule understands (at most twice per job)."""
        ai = self.ctx.ai
        if ai is None or not ai.enabled or self.state.ai_repairs >= 2:
            return False
        line = issue.line or 0
        start, end, excerpt = self._excerpt(line)
        if not excerpt:
            return False
        answer = ai.ask("latex_repair", AI_REPAIR_SYSTEM,
                        AI_REPAIR_PROMPT.format(error=issue.message, line=line, start=start, end=end, excerpt=excerpt))
        if not answer:
            return False
        patch, provider = answer
        self.state.ai_repairs += 1
        applied = self.apply_patch(patch, start, end, provider, issue.kind, issue.message,
                                   str(patch.get("explanation", "")))
        step = f"{STEP} (pass {self.iteration})"
        if applied:
            ai.record(step, "ai", "Patched a line for an error no rule understands.", provider)
        else:
            ai.reject(step, provider, "its line patch could not be applied safely")
        return applied

    def apply_patch(self, patch: dict, start: int, end: int, provider: str, kind: str, message: str,
                    explanation: str = "") -> bool:
        """Apply a small AI line patch inside the excerpt range, only if it keeps the author's words."""
        lines = self.tex.split("\n")
        try:
            first, last = int(patch.get("line_start", 0)), int(patch.get("line_end", 0))
        except (TypeError, ValueError):
            return False
        replacement = str(patch.get("replacement", ""))
        if not (start <= first <= last <= end) or last - first > 6 or last > len(lines):
            self.ctx.log(STEP, f"{provider} suggested an out-of-range or too-large edit; ignored.", "warning")
            return False
        original = "\n".join(lines[first - 1 : last])
        if not _keeps_words(original, replacement):
            self.ctx.log(STEP, f"{provider} suggested an edit that removes text; ignored.", "warning")
            return False
        sig = f"ai:{message[:60]}:{first}"
        if sig in self.state.applied or replacement == original:
            return False
        lines[first - 1 : last] = replacement.split("\n")
        self.tex = "\n".join(lines)
        self._record(sig, kind, f"AI fix for '{message[:80]}' on lines {first}-{last}: {explanation[:120]}", source=provider)
        return True

    # ------------------------------------------------------------- repair agent (Full mode)
    def _problems(self, result: CompileResult) -> list[LogIssue]:
        """Issues worth the agent's attention this pass (empty when there is nothing to fix)."""
        threshold = self._overfull_threshold()
        bib = self._bib_keys()
        out = []
        for i in result.issues:
            if (i.severity == "error" or i.kind in {"missing_file", "missing_package", "unicode_error", "fatal_error"}
                    or (i.kind == "undefined_citation" and i.target and i.target not in bib)
                    or (i.kind == "overfull_hbox" and (i.amount_pt or 0) > threshold)):
                out.append(i)
        return out

    def try_agent(self, result: CompileResult, problems: list[LogIssue]) -> tuple[bool, str | None, int]:
        """Ask the repair agent which tools to use. Returns (changed, provider, number of repairs it proposed), or
        (False, None, 0) without an answer."""
        anchor = next((i.line for i in problems if i.kind == "fatal_error" and i.line), None) or next(
            (i.line for i in problems if i.line), None)
        start, end, excerpt = self._excerpt(anchor or 0)
        issues = "\n".join(
            f"- [{i.kind}] {i.message[:200]}" + (f" (line {i.line})" if i.line else "")
            + (f" target={i.target}" if i.target else "") for i in problems[:15])
        prompt = AGENT_PROMPT.format(
            iteration=self.iteration, venue=self.spec.display_name,
            status="compiled to PDF" if result.success else "no PDF produced", issues=issues,
            excerpt=f"main.tex lines {start}-{end}:\n{excerpt}\n" if excerpt else "",
            missing=", ".join(self.project.missing_figures[:20]) or "none",
            bib_keys=", ".join(sorted(self._bib_keys())[:60]) or "none")
        answer = self.ctx.ai.ask("repair_agent", AGENT_SYSTEM, prompt)
        if not answer:
            return False, None, 0
        reply, provider = answer
        actions = reply.get("actions")
        explanation = str(reply.get("explanation", ""))[:160]
        if not isinstance(actions, list):
            return False, provider, 0
        self.source = provider
        changed = False
        try:
            for action in actions[:12]:
                if isinstance(action, dict):
                    changed = self._run_tool(action, start, end, provider, explanation) or changed
        finally:
            self.source = "deterministic"
        if explanation and changed:
            self.ctx.log(STEP, f"Repair agent ({provider}): {explanation}")
        elif explanation:
            self.ctx.log(STEP, f"Repair agent ({provider}) had no usable fix; it suggested: {explanation}")
        return changed, provider, len(actions)

    def _run_tool(self, action: dict, start: int, end: int, provider: str, explanation: str) -> bool:
        """Run one tool call from the agent. Every argument is checked; anything invalid is ignored."""
        tool = str(action.get("tool", ""))
        name = str(action.get("name", "")).strip()
        if tool == "allow_downloads":
            return self._allow_downloads("missing_package", "Allowed the compiler to download a LaTeX package that is "
                                                            "not cached")
        if tool == "add_package":
            return self._agent_add_package(name, provider)
        if tool == "remove_package":
            valid = PACKAGE_NAME.fullmatch(name) and name not in ESSENTIAL_PACKAGES
            return bool(valid) and self._drop_package(name, "missing_package", f"Removed \\usepackage{{{name}}}")
        if tool == "placeholder_figure":
            return self.fix_missing_file(Path(str(action.get("file", ""))).name)
        if tool == "remove_citation":
            return self.remove_citation(str(action.get("key", "")).strip())
        if tool == "replace_command":
            return self._agent_replace_command(str(action.get("old", "")).strip(), str(action.get("new", "")).strip())
        if tool == "define_theorem":
            title = re.sub(r"[^A-Za-z ]", "", str(action.get("title", ""))).strip()[:30] or name.title()
            return bool(re.fullmatch(r"[a-z]+", name)) and self._define_theorem(name, title)
        if tool == "scale_table":
            try:
                return self.scale_table_at(int(action.get("line", 0)))
            except (TypeError, ValueError):
                return False
        if tool == "sloppy":
            return self.make_sloppy()
        if tool == "patch_lines" and start:
            return self.apply_patch(action, start, end, provider, "fatal_error", "compile error", explanation)
        return False

    def _agent_add_package(self, name: str, provider: str) -> bool:
        if not PACKAGE_NAME.fullmatch(name):
            return False
        if name in self.spec.content_rules.forbidden_packages:
            self.ctx.log(STEP, f"{provider} wanted \\usepackage{{{name}}}, which this venue forbids; ignored.", "warning")
            return False
        sig = f"agent_add:{name}"
        if sig in self.state.applied or not self._add_package(name):
            return False
        self._record(sig, "fatal_error", f"Added \\usepackage{{{name}}}")
        return True

    def _agent_replace_command(self, old: str, new: str) -> bool:
        if not (COMMAND_NAME.fullmatch(old) and COMMAND_NAME.fullmatch(new)) or old == new or old in PROTECTED_COMMANDS:
            return False
        sig = f"agent_replace:{old}"
        if sig in self.state.applied or not re.search(re.escape(old) + r"(?![A-Za-z])", self.tex):
            return False
        self._replace_command(old, new)
        self._record(sig, "fatal_error", f"Replaced {old} with {new}")
        return True


def _keeps_words(original: str, replacement: str) -> bool:
    """True if the replacement keeps at least 90% of the original's words (LaTeX commands ignored)."""
    def words(text: str) -> list[str]:
        return re.findall(r"[A-Za-z]{3,}", re.sub(r"\\[A-Za-z]+", " ", text))

    old_words, new_words = words(original), set(words(replacement))
    return not old_words or sum(w in new_words for w in old_words) / len(old_words) >= 0.9


def run(ctx: StepContext, repairer: Repairer, result: CompileResult, iteration: int) -> bool:
    """Log what the compile found and repair it. Returns True if main.tex changed."""
    errors = sum(i.severity == "error" for i in result.issues)
    warnings = sum(i.severity == "warning" for i in result.issues)
    ctx.log(STEP, f"Iteration {iteration}: {errors} error(s), {warnings} warning(s) in the compile log",
            "warning" if errors else "info")
    changed = repairer.repair(result, iteration)
    if not changed and errors:
        ctx.log(STEP, "No automatic repair is available for the remaining error(s).", "warning")
    return changed
