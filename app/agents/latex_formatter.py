"""Step 4 - LaTeX Formatter: ManuscriptStructure + VenueSpec -> LaTeX project on disk.

In Full agentic mode a Formatter agent first makes the layout decisions for
this paper (which figures and tables span both columns, which extra packages
to drop) and lists anything the author should check. Its answer can only pick
from the paper's own figures, tables and packages. The LaTeX itself is always
produced by templating: the venue's bundled class/style files are copied
unchanged and content is rendered through the venue's Jinja2 template.
"""

from __future__ import annotations

import json
import re
import shutil
import unicodedata
from pathlib import Path

from app.agents.base import StepContext
from app.agents.text_fixes import EQUATION_REF, TextFixer
from app.agents.venue_analyst import template_dir
from app.formatters import figures as fig_utils
from app.formatters.latex_renderer import render
from app.formatters.markdown_to_latex import cited_names, inline_md, natbib_citations, normalize_citations
from app.formatters.tables import column_count, is_wide, render_table
from app.models.latex import LaTeXProject
from app.models.manuscript import ManuscriptStructure, Section, TextBlock
from app.models.venue import VenueSpec
from app.parsers.bibtex_parser import write_bibtex
from app.parsers.latex_parser import INCLUDEGRAPHICS_RE, expand_macros, find_command, latex_to_plain
from app.parsers.text_utils import (LATEX_SPECIALS, T1_MISMATCHED, UNICODE_TO_LATEX, latex_escape, normalize_space,
                                    t1_safe)

STEP = "LaTeX Formatter"
SECTION_CMDS = {1: "section", 2: "subsection", 3: "subsubsection", 4: "paragraph"}
# Every venue template loads the common packages itself; fonts, encodings and the citation package are the
# venue's choice. The paper's own \usepackage lines for these are dropped.
TEMPLATE_PACKAGES = {"cite", "amsmath", "amssymb", "amsfonts", "graphicx", "textcomp", "xcolor",
                     "url", "array", "inputenc", "fontenc", "natbib", "biblatex", "lmodern", "times", "mathptmx"}
# Style files of other venues (the paper may have been written for one): the target venue's style replaces them.
VENUE_STYLE_RE = re.compile(r"(acl|acl\d+|naacl\w*|emnlp\w*|coling\w*|neurips_?\d*|nips_?\d*|icml\d+|iclr\d+_conference"
                            r"|colm\d+_conference|cvpr|iccv|eccv|wacv|aaai\d*|ijcai\d*|kdd\w*|sig-alternate|usenix\w*"
                            r"|jmlr\w*|tmlr|llncsdoc|spconf)")

THEOREM_ENVS = {"theorem": "Theorem", "lemma": "Lemma", "definition": "Definition", "corollary": "Corollary",
                "proposition": "Proposition", "remark": "Remark", "example": "Example", "assumption": "Assumption",
                "claim": "Claim", "conjecture": "Conjecture"}
# Classes such as llncs and acmart define these environments; the venue class may not. Each is defined at
# \begin{document} only if nothing defined it by then, so a class that has its own keeps it.
PROOF_FALLBACK = (r"\AtBeginDocument{\ifdefined\proof\else\newenvironment{proof}"
                  r"{\par\noindent\emph{Proof.}\ }{\hfill\rule{1ex}{1ex}\par}\fi}")
QED_FALLBACK = r"\AtBeginDocument{\providecommand{\qed}{\hfill\rule{1ex}{1ex}}\providecommand{\qedhere}{}}"
# Abbreviations that cvpr.sty defines (\eg, \etal, ...); spelled out for a venue whose style file does not.
ABBREVIATIONS = {"eg": "e.g.", "Eg": "E.g.", "ie": "i.e.", "Ie": "I.e.", "cf": "cf.", "Cf": "Cf.", "etc": "etc.",
                 "vs": "vs.", "wrt": "w.r.t.", "dof": "d.o.f.", "iid": "i.i.d.", "wolog": "w.l.o.g.", "etal": "et al."}
WIDE_TABLE_COLUMNS = 7
ROMAN_NUMERALS = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII", "XIII", "XIV", "XV"]
TEX_TO_UNICODE = {tex: ch for ch, tex in UNICODE_TO_LATEX.items() if tex.startswith("\\ensuremath")}
DISPLAY_MATH_ENV = re.compile(r"\\begin\{(equation|align|gather|multline|eqnarray)\*?\}")


def _blocks(sections: list[Section]):
    """Every block of these sections and their subsections, in reading order."""
    for section in sections:
        yield from section.blocks
        yield from _blocks(section.subsections)


def same_paragraph(previous: TextBlock, block: TextBlock, rendered: str) -> bool:
    """A display equation is part of the sentence around it. A blank line before it would add a gap, and one
    after it would indent the "where" that carries the sentence on."""
    if block.kind == "equation":
        return previous.kind in {"paragraph", "equation"}
    return previous.kind == "equation" and block.kind == "paragraph" and rendered[:1].islower()


def environment_fallbacks(body: str) -> list[str]:
    used = set(re.findall(r"\\begin\{([a-z]+)\}", body))
    lines = [rf"\AtBeginDocument{{\ifdefined\{env}\else\newtheorem{{{env}}}{{{title}}}\fi}}"
             for env, title in THEOREM_ENVS.items() if env in used]
    description = "\\providecommand{\\Description}[2][]{}"  # ACM's figure descriptions, kept for other venues
    qed = re.search(r"\\qed(?:here)?(?![A-Za-z])", body)
    return lines + [PROOF_FALLBACK] * ("proof" in used) + [QED_FALLBACK] * bool(qed) + [description] * (
        "\\Description" in body)


def tabular_columns(latex: str) -> int:
    """Columns of the first tabular in ``latex``, counted from its first row."""
    start = re.search(r"\\begin\{tabular[x*]?\}", latex)
    if not start:
        return 0
    rows = re.sub(r"\\(toprule|midrule|hline)\b", "", latex[start.end():])
    first_row = re.split(r"\\\\", rows, maxsplit=1)[0]
    return len(re.findall(r"(?<!\\)&", first_row)) + 1


def split_title_notes(title: str) -> tuple[str, list[str]]:
    """'Title\\thanks{Funded.}' -> ('Title', ['Funded.']), for classes such as acmart that take \\titlenote."""
    notes = []
    while found := find_command(title, "thanks"):
        start, _, note, end = found
        notes.append(note)
        title = title[:start] + title[end:]
    return title.strip(), notes


def sorted_terms(terms: list[str]) -> list[str]:
    """Alphabetical order. When only the first term was capitalized, the capital stays on whichever term comes first."""
    ordered = sorted(terms, key=str.casefold)
    first = terms[0]
    first_word = first.split()[0] if first.split() else ""
    if (ordered[0] != first and first_word[:1].isupper() and first_word[1:].isalpha() and first_word[1:].islower()
            and all(t[:1].islower() for t in terms[1:])):
        ordered = [first[0].lower() + first[1:] if t == first else t for t in ordered]
        ordered[0] = ordered[0][0].upper() + ordered[0][1:]
    return ordered


def pdf_text(tex: str) -> str:
    """Plain text for PDF metadata. acmart copies the title there, where math commands stop the build."""
    text = re.sub(r"\$(\\[A-Za-z]+)\$", r"\\ensuremath{\1}", tex)
    text = re.sub(r"\\ensuremath\{(?:[^{}]|\{[^{}]*\})*\}", lambda m: TEX_TO_UNICODE.get(m[0], m[0]), text)
    text = re.sub(r"\\[^A-Za-z]", " ", latex_to_plain(text)).replace("$", "")
    text = unicodedata.normalize("NFKC", normalize_space(text))
    return "".join(LATEX_SPECIALS.get(ch, ch) for ch in text if ch not in T1_MISMATCHED)


PLAN_SYSTEM = (
    "You are the LaTeX Formatter agent of a paper-formatting pipeline. You decide the layout of a paper "
    "for a venue template. You never change the author's text. Return only JSON."
)
PLAN_PROMPT = """Venue: {venue} ({columns}-column, {paper} paper, page limit {pages}).
Packages the venue forbids: {forbidden}.
The paper (already parsed):
{paper_json}

Decide the layout and return JSON:
{{"wide_figures": ["<figure ids that must span both columns>"],
 "wide_tables": ["<table ids that must span both columns>"],
 "drop_packages": ["<extra packages from the paper that conflict with the venue template>"],
 "notes": ["<short layout problem the author should check>"]}}
Rules: in a 2-column layout, use full width only for figures or tables too wide or detailed for one
column (for example images much wider than tall, or tables with many columns or long cells). Everything
not listed stays single-column. Only use ids and package names that appear above. A note must name a
concrete problem you can see in the data above (with the figure or table id); leave "notes" empty rather
than give general advice. At most 5 notes."""


def _image_aspect(path: Path) -> float | None:
    try:
        import pymupdf

        if path.suffix.lower() == ".pdf":
            with pymupdf.open(path) as doc:
                rect = doc[0].rect
                return round(rect.width / rect.height, 2) if rect.height else None
        pix = pymupdf.Pixmap(str(path))
        return round(pix.width / pix.height, 2) if pix.height else None
    except Exception:
        return None


def _package_names(usepackage_line: str) -> list[str]:
    """'\\usepackage[opt]{a, b}' -> ['a', 'b']"""
    m = re.search(r"\{([^}]+)\}", usepackage_line)
    return [n.strip() for n in m.group(1).split(",") if n.strip()] if m else []


def plan_input(m: ManuscriptStructure, upload_dir: Path) -> dict:
    figures = []
    for f in m.figures[:40]:
        src = fig_utils.resolve_figure(f.file, upload_dir) if f.file else None
        figures.append({"id": f.id, "caption": f.caption[:140], "currently_wide": f.wide,
                        "aspect_ratio_w_h": _image_aspect(src) if src else None})
    tables = []
    for t in m.tables[:40]:
        if t.raw_latex:
            continue
        longest = max([len(c) for r in [t.header, *t.rows] for c in r] + [0])
        tables.append({"id": t.id, "caption": t.caption[:140], "columns": column_count(t), "rows": len(t.rows),
                       "longest_cell_chars": longest})
    packages = [name for line in m.preamble_extras.packages for name in _package_names(line)]
    return {"figures": figures, "tables": tables, "extra_packages": packages,
            "sections": [s.title[:80] for s in m.sections][:30]}


def apply_plan(plan: dict, m: ManuscriptStructure, spec: VenueSpec) -> tuple[ManuscriptStructure, list[str], list[str]]:
    """Apply the agent's layout plan. Returns (manuscript, changes, notes for the author)."""
    m = m.model_copy(deep=True)
    lists = ("wide_figures", "wide_tables", "drop_packages", "notes")
    if any(plan.get(key) is not None and not isinstance(plan[key], list) for key in lists):
        return m, [], []  # an answer of the wrong shape is unusable: the template's rules decide the layout
    changes: list[str] = []
    two_col = spec.layout.columns == 2
    wide_figs = {str(x) for x in plan.get("wide_figures") or []}
    wide_tabs = {str(x) for x in plan.get("wide_tables") or []}
    if two_col:
        for f in m.figures:
            want = f.id in wide_figs
            if want != f.wide:
                f.wide = want
                changes.append(f"figure {f.id} {'full width' if want else 'single column'}")
        for t in m.tables:
            if t.raw_latex:
                continue
            want = t.id in wide_tabs
            before = is_wide(t)
            t.wide, t.wide_decided = want, True
            if before != want:
                changes.append(f"table {t.id} {'full width' if want else 'single column'}")
    drop = {str(x).strip() for x in plan.get("drop_packages") or [] if re.fullmatch(r"[A-Za-z0-9\-]+", str(x).strip())}
    drop -= TEMPLATE_PACKAGES
    if drop:
        kept = []
        for line in m.preamble_extras.packages:
            names = _package_names(line)
            if names and all(n in drop for n in names):
                changes.append(f"dropped \\usepackage{{{','.join(names)}}}")
                continue
            kept.append(line)
        m.preamble_extras.packages = kept
    notes = [normalize_space(str(n))[:200] for n in (plan.get("notes") or [])[:5] if str(n).strip()]
    return m, changes, notes


class Formatter:
    def __init__(self, manuscript: ManuscriptStructure, spec: VenueSpec, templates_root: Path,
                 upload_dir: Path, work_dir: Path) -> None:
        self.m = manuscript
        self.spec = spec
        self.tdir = template_dir(spec.template.directory, templates_root)
        self.upload_dir = upload_dir
        self.work_dir = work_dir
        self.figures_dir = work_dir / "figures"
        self.project = LaTeXProject(root_dir=str(work_dir))
        self.notes: list[str] = []
        self._fig_cache: dict[str, str | None] = {}
        self.review = spec.content_rules.anonymous_submission
        self.names = cited_names(manuscript.references)
        self.style_files = "\n".join(f.read_text(encoding="utf-8", errors="replace")
                                     for f in self.tdir.iterdir() if f.suffix in {".sty", ".cls"})
        natbib = [line for line in manuscript.preamble_extras.packages if "natbib" in _package_names(line)]
        styles = [n for line in manuscript.preamble_extras.packages for n in _package_names(line)]
        # In an author-year paper \cite already means "Author (Year)"; in a numbered paper it was a bracket.
        self.cite_is_textual = (bool(natbib) and "numbers" not in natbib[0]) or any(
            re.match(r"(iclr|icml|neurips|nips|colm)", n) for n in styles)

    # ---------------------------------------------------------------- text helpers
    def text(self, value: str, fmt: str | None = None) -> str:
        """Manuscript text as LaTeX. ``fmt`` is the block's format; the manuscript's format by default."""
        fmt = fmt or self.m.text_format
        if fmt == "markdown":
            return self.cite(inline_md(value))
        if fmt == "plain":
            return latex_escape(value)
        return self.cite(value)

    def cite(self, latex: str) -> str:
        """Citation commands the venue's class understands: plain \\cite for IEEEtran, natbib's otherwise."""
        style = self.spec.template.citations
        if style == "cite":
            return normalize_citations(latex, self.names)
        latex = natbib_citations(latex)
        if style == "natbib_author_year" and not self.cite_is_textual:
            latex = re.sub(r"\\cite(?=[\[{])", r"\\citep", latex)  # a numbered paper's [3] reads as (Author, Year)
        return latex

    def figure_file(self, ref: str) -> str | None:
        """Resolve and copy a figure. Returns the file name to use in LaTeX, or None."""
        if ref in self._fig_cache:
            return self._fig_cache[ref]
        src = fig_utils.resolve_figure(ref, self.upload_dir)
        name: str | None = None
        if src is None:
            self.project.missing_figures.append(ref)
        else:
            name, problem = fig_utils.prepare_figure(src, self.figures_dir)
            if problem:
                self.project.unconverted_figures.append(src.name)
                self.notes.append(problem)
            elif name and name not in self.project.figure_files:
                self.project.figure_files.append(f"figures/{name}")
        self._fig_cache[ref] = name
        return name

    def fit_floats(self, latex: str) -> str:
        """In a two-column layout, make the paper's own figure and table floats fit: a figure the layout plan
        made wide (or narrow) switches between figure* and figure, and widths given as \\textwidth (the full
        page in a one-column paper) become the float's own width."""
        if self.spec.layout.columns != 2:
            return latex
        wide_files = {f.file for f in self.m.figures if f.wide}

        def fit(m: re.Match) -> str:
            env, inner = m.group(1), m.group(3)
            graphic = INCLUDEGRAPHICS_RE.search(inner)
            if env == "figure" and graphic:
                wide = graphic.group(1).strip() in wide_files
            else:  # a table with many columns is unreadable when squeezed into one column
                wide = bool(m.group(2)) or tabular_columns(inner) >= WIDE_TABLE_COLUMNS
            inner = inner.replace("\\textwidth", "\\linewidth").replace("\\columnwidth", "\\linewidth")
            name = env + ("*" if wide else "")
            return f"\\begin{{{name}}}{inner}\\end{{{name}}}"

        return re.sub(r"\\begin\{(figure|table)(\*?)\}(.*?)\\end\{\1\2\}", fit, latex, flags=re.S)

    def spell_abbreviations(self, latex: str) -> str:
        """\\eg and the like, as cvpr.sty prints them, for a venue whose style file does not define them."""
        defined = "\n".join(self.m.preamble_extras.macros) + self.style_files
        missing = [name for name in ABBREVIATIONS
                   if not re.search(rf"\\(?:def|(?:new|provide)command\*?\s*\{{?)\\{name}(?![A-Za-z])", defined)]

        def spell(m: re.Match) -> str:
            text = ABBREVIATIONS[m.group(1)][:-1] if m.group(2) else ABBREVIATIONS[m.group(1)]
            space = m.group(3)
            if space and latex[m.end():m.end() + 1].islower():
                space = "\\ "  # "e.g.\ the": a space between words, not after a sentence
            return text + (m.group(2) or "") + space

        if not missing:
            return latex
        return re.sub(rf"\\({'|'.join(missing)})(?![A-Za-z])(?:\{{\}})?(\.)?(\s*)", spell, latex)

    def rewrite_raw_latex(self, latex: str) -> str:
        latex = self.spell_abbreviations(self.cite(self.fit_floats(latex)))

        def repl(m: re.Match) -> str:
            ref = m.group(1).strip()
            name = self.figure_file(ref)
            if name:
                return m.group(0).replace("{" + m.group(1) + "}", "{" + name + "}")
            if any(Path(u).stem == Path(ref).stem for u in self.project.unconverted_figures):
                return fig_utils.placeholder(Path(ref).name)
            # Keep the reference to the missing file; QA reports and repairs it.
            return m.group(0).replace("{" + m.group(1) + "}", "{" + Path(ref).name + "}")

        return INCLUDEGRAPHICS_RE.sub(repl, latex)

    def label_floats(self) -> None:
        """Word and Markdown papers have no labels: give every captioned figure and table one, so a typed
        "Table 1" can point at it."""
        if self.m.source.format not in {"docx", "md"}:
            return
        for item in [f for f in self.m.figures if f.caption] + [t for t in self.m.tables if t.caption]:
            item.label = item.label or f"pf:{item.id}"

    def label_equations(self) -> None:
        """Word and Markdown papers have no equation labels: give each display equation one, so a typed "Eq. (2)"
        can point at it. Only when the paper's equation numbers can be followed."""
        self.equation_labels: dict[str, str] = {}
        if self.m.source.format not in {"docx", "md"}:
            return
        number = 0
        for block in _blocks(self.m.sections + self.m.appendices):
            if block.kind == "raw_latex" and DISPLAY_MATH_ENV.search(block.content) or (
                    block.kind == "equation" and DISPLAY_MATH_ENV.match(block.content.strip())):
                self.equation_labels = {}
                return
            if block.kind == "equation":
                rows = re.sub(r"\\begin\{(\w+\*?)\}.*?\\end\{\1\}", "", block.content, flags=re.S)
                number += rows.strip().rstrip("\\").count("\\\\") + 1
                block.label = block.label or f"pf:eq{number}"
                self.equation_labels[str(number)] = block.label

    def link_numbers(self, latex: str) -> str:
        """'Table 1', 'Table I', 'Fig. 2' or 'Eq. (3)' typed in a Word or Markdown paper becomes Table~\\ref{...},
        so the number matches the venue's own numbering (IEEE, for one, prints tables as TABLE I)."""
        if self.m.source.format not in {"docx", "md"}:
            return latex
        latex = EQUATION_REF.sub(lambda m: m.group(1) + "~" + re.sub(
            r"\(?\b(\d+)\b\)?", lambda n: f"\\eqref{{{self.equation_labels[n.group(1)]}}}"
            if n.group(1) in self.equation_labels else n.group(0), m.group(2)), latex)
        floats = {"tab": [t for t in self.m.tables if t.caption], "fig": [f for f in self.m.figures if f.caption]}

        def link(m: re.Match) -> str:
            items = floats["tab" if m.group(1).lower().startswith("tab") else "fig"]
            number = m.group(3)
            n = int(number) if number.isdigit() else ROMAN_NUMERALS.index(number) + 1
            return f"{m.group(1)}~\\ref{{{items[n - 1].label}}}" if 0 < n <= len(items) else m.group(0)

        roman = "|".join(sorted(ROMAN_NUMERALS, key=len, reverse=True))
        return re.sub(rf"(?<![\w\\])([Tt]able|[Tt]ab\.|[Ff]igure|[Ff]ig\.)(\s|~)+(\d+|{roman})\b(?![.,]\d)", link, latex)

    # ---------------------------------------------------------------- blocks
    def render_block(self, block: TextBlock) -> str:
        if block.kind == "raw_latex":
            return self.rewrite_raw_latex(block.content)
        if block.kind == "paragraph":
            return self.link_numbers(self.text(block.content, block.format))
        if block.kind == "equation":
            body = block.content.strip()
            if DISPLAY_MATH_ENV.match(body):
                return body
            label = f"\\label{{{block.label}}}" if block.label else ""
            rows = re.sub(r"\\begin\{(\w+\*?)\}.*?\\end\{\1\}", "", body, flags=re.S)  # a matrix's rows don't count
            if "\\\\" in rows:
                return f"\\begin{{align}}\n{body}{label}\n\\end{{align}}"
            return f"\\begin{{equation}}\n{body}{label}\n\\end{{equation}}"
        if block.kind == "list":
            env = "enumerate" if block.ordered else "itemize"
            items = "\n".join(f"\\item {self.link_numbers(self.text(i, block.format))}" for i in block.items)
            return f"\\begin{{{env}}}\n{items}\n\\end{{{env}}}"
        if block.kind == "code":
            code = block.content.replace("\\end{verbatim}", "\\end {verbatim}")
            return f"{{\\footnotesize\n\\begin{{verbatim}}\n{code}\n\\end{{verbatim}}\n}}"
        if block.kind == "figure_ref":
            fig = next((f for f in self.m.figures if f.id == block.content), None)
            if not fig:
                return ""
            name = self.figure_file(fig.file) if fig.file else None
            return fig_utils.render_figure(fig, name, self.text)
        if block.kind == "table_ref":
            table = next((t for t in self.m.tables if t.id == block.content), None)
            if not table:
                return ""
            return render_table(table, self.text, self.spec.content_rules.table_caption)
        return ""

    def render_section(self, section: Section) -> str:
        parts = []
        title = section.title
        if title != "*":
            starred = title.startswith("*")
            title = title.lstrip("*").strip()
            if section.level >= 3 and self.spec.template.class_punctuates_run_in_headings:
                title = re.sub(r"(?<!\.)\.$", "", title)  # "Spill Policy." would print as "Spill Policy.:"
            cmd = SECTION_CMDS.get(section.level, "paragraph")
            parts.append(f"\\{cmd}{'*' if starred else ''}{{{self.text(title)}}}")
            if section.label:
                parts.append(f"\\label{{{section.label}}}")
        previous = None
        for block in section.blocks:
            rendered = self.render_block(block).strip()
            if not rendered:
                continue
            if previous and same_paragraph(previous, block, rendered):
                parts[-1] += "\n" + rendered
            else:
                parts.append(rendered)
            previous = block
        for sub in section.subsections:
            parts.append(self.render_section(sub))
        return "\n\n".join(parts)

    # ---------------------------------------------------------------- front matter
    def authors_context(self) -> tuple[list[dict], list[str]]:
        """(authors, affiliations). Each author has a name, email, affiliations, affiliation_lines (affiliations
        then email, one per line) and marks (1-based numbers into the shared affiliation list)."""
        if self.review:  # the source must not name the authors either, so the class's review mode gets placeholders
            people = [("Anonymous Author(s)", ["Anonymous Institution"], "")]
        else:
            people = [(a.name, [x for x in a.affiliations if x.strip()], a.email or "") for a in self.m.authors]
        if not people:
            people = [("Author Name", ["Affiliation"], "")]
            self.notes.append("No authors were found; a placeholder author block was inserted.")
        affiliations = list(dict.fromkeys(latex_escape(x) for _, affs, _ in people for x in affs))
        authors = []
        for name, affs, email in people:
            escaped = [latex_escape(x) for x in affs]
            authors.append({"name": latex_escape(name), "email": latex_escape(email), "affiliations": escaped,
                            "affiliation_lines": escaped + ([latex_escape(email)] if email else []),
                            "marks": [affiliations.index(x) + 1 for x in escaped]})
        return authors, affiliations

    def preamble_extras(self, body: str) -> tuple[list[str], list[str]]:
        forbidden = set(self.spec.content_rules.forbidden_packages)
        provided = TEMPLATE_PACKAGES | set(self.spec.template.loads_packages)
        packages: list[str] = []
        for line in self.m.preamble_extras.packages:
            names = _package_names(line)
            if names and all(n in provided for n in names):
                continue
            if names and all(VENUE_STYLE_RE.fullmatch(n) for n in names):
                self.notes.append(f"Removed \\usepackage{{{','.join(names)}}}: another venue's style; "
                                  f"{self.spec.display_name} uses its own.")
                continue
            if names and all(n in forbidden for n in names):
                self.notes.append(f"Removed \\usepackage{{{','.join(names)}}}: not allowed by {self.spec.display_name}.")
                continue
            if line not in packages:
                packages.append(line)
        macros = list(self.m.preamble_extras.macros) + environment_fallbacks(body)
        loaded = {name for line in packages for name in _package_names(line)}
        if loaded & {"caption", "subcaption"}:
            macros = self.spec.template.caption_setup + macros
        if self.spec.template.citations == "natbib_author_year" and self.bibliography_items():
            # A typed reference list has no author-year data, so natbib numbers its citations.
            macros.append(r"\setcitestyle{numbers,square}")
            if "\\cite" in body:
                self.notes.append("Your references are a typed list, so citations are numbered [1] instead of this "
                                  "venue's author-year style (Lee et al., 2020). Upload your references as a .bib "
                                  "file to get author-year citations.")
        return packages, macros

    def bibliography_items(self) -> list:
        """References typed as a list (not BibTeX entries)."""
        if any(r.origin == "bibtex" for r in self.m.references):
            return []
        return [r for r in self.m.references if r.origin in {"thebibliography", "reference_list_text"}]

    def bibliography(self) -> tuple[str | None, str | None]:
        """Returns (bib file stem, thebibliography LaTeX)."""
        bib_refs = [r for r in self.m.references if r.origin == "bibtex"]
        if bib_refs:
            (self.work_dir / "references.bib").write_text(write_bibtex(bib_refs), encoding="utf-8")
            self.project.bib_file = "references.bib"
            return "references", None
        self.project.bib_file = None
        items = self.bibliography_items()
        if not items:
            return None, None
        lines = [f"\\begin{{thebibliography}}{{{max(9, len(items))}}}"]
        for r in items:
            raw = r.fields.get("raw", "")
            if r.origin == "reference_list_text":
                raw = self.text(raw)
            lines.append(f"\\bibitem{{{r.key}}}\n{raw}")
        lines.append("\\end{thebibliography}")
        return None, "\n\n".join(lines)  # hyperref's backref (CVPR) needs a paragraph break after each item

    # ---------------------------------------------------------------- main
    def build(self) -> LaTeXProject:
        if self.work_dir.exists():
            shutil.rmtree(self.work_dir)
        self.work_dir.mkdir(parents=True)
        self.figures_dir.mkdir()
        tmpl = self.spec.template
        for f in tmpl.files:
            if f.copy_to_output:
                shutil.copyfile(self.tdir / f.path, self.work_dir / Path(f.path).name)
                self.project.template_files.append(Path(f.path).name)

        self.label_floats()
        self.label_equations()
        body_chunks = [self.render_section(s) for s in self.m.sections]
        appendix_chunks = [self.render_section(s) for s in self.m.appendices]
        author_year = self.spec.template.citations == "natbib_author_year" and not self.bibliography_items()
        fixer = TextFixer(self.spec.content_rules, body_chunks + appendix_chunks, author_year, len(appendix_chunks),
                          self.names, self.spec.template.loads_packages, [r.key for r in self.bibliography_items()])
        abstract = fixer.fix_abstract(self.text(self.m.abstract)) if self.m.abstract else ""
        body_chunks = [fixer.fix(chunk) for chunk in body_chunks]
        appendix_chunks = [fixer.fix(chunk) for chunk in appendix_chunks]
        self.project.changes = fixer.changes
        body_text = "\n".join(body_chunks + appendix_chunks)
        if tmpl.split_sections and tmpl.section_template:
            (self.work_dir / "sections").mkdir()
            new_chunks = []
            for idx, chunk in enumerate(body_chunks, 1):
                name = f"sections/{idx:02d}.tex"
                content = t1_safe(render(self.tdir, tmpl.section_template, {"content": chunk}))
                (self.work_dir / name).write_text(content, encoding="utf-8")
                self.project.section_files.append(name)
                new_chunks.append(f"\\input{{{name[:-4]}}}")
            body_chunks = new_chunks

        bib_stem, thebib = self.bibliography()
        packages, macros = self.preamble_extras(body_text)
        keywords = [latex_escape(k) for k in self.m.keywords]
        if keywords and not self.spec.content_rules.keywords.printed:
            self.notes.append("This venue's papers have no keywords, so yours were left out.")
        if self.spec.content_rules.sort_keywords and keywords != sorted(keywords, key=str.casefold):
            keywords = sorted_terms(keywords)
            self.project.changes.append("Keywords (Index Terms): put in alphabetical order: "
                                        f"{', '.join(sorted_terms(self.m.keywords))}.")
        acknowledgments = self.text(self.m.acknowledgments or "")
        if acknowledgments and self.review:
            acknowledgments = ""
            self.notes.append("Acknowledgements are left out of the anonymous submission; the camera-ready "
                              "version includes them.")
        authors, affiliations = self.authors_context()
        title = self.text(self.m.title) or "Untitled Paper"
        bare_title, title_notes = split_title_notes(title)
        context = {
            "venue_name": self.spec.display_name,
            "document_class": tmpl.document_class,
            "class_options": ",".join(tmpl.class_options),
            "review": self.review,
            "extra_packages": packages,
            "macros": macros,
            "title": title,
            "bare_title": bare_title,
            "title_notes": title_notes,
            "pdf_title": pdf_text(expand_macros(bare_title, self.m.preamble_extras.macros)),
            "authors": authors,
            "affiliations": affiliations,
            "abstract": abstract or "Abstract not found in the uploaded manuscript.",
            "keywords": keywords,
            "body_chunks": body_chunks,
            "appendix_chunks": appendix_chunks,
            "acknowledgments": acknowledgments,
            "ccs": self.m.ccs or "",
            "bibliography_file": bib_stem,
            "bibliography_style": tmpl.bibliography_style or "plain",
            "thebibliography": thebib,
        }
        main = t1_safe(render(self.tdir, tmpl.main_template, context))
        main = re.sub(r"\n{3,}", "\n\n", main)
        (self.work_dir / self.project.main_file).write_text(main, encoding="utf-8")
        if not self.m.title:
            self.notes.append("No title was found; 'Untitled Paper' was used.")
        if not self.m.abstract:
            self.notes.append("No abstract was found; a placeholder sentence was inserted.")
        return self.project


def _plan_step(ctx: StepContext, manuscript: ManuscriptStructure, spec: VenueSpec
               ) -> tuple[ManuscriptStructure, list[str]] | None:
    pl = spec.layout.page_limit
    pages = f"{pl.max_pages_main} pages" if pl.max_pages_main else "none"
    prompt = PLAN_PROMPT.format(venue=spec.display_name, columns=spec.layout.columns, paper=spec.layout.paper_size,
                                pages=pages, forbidden=", ".join(spec.content_rules.forbidden_packages) or "none",
                                paper_json=json.dumps(plan_input(manuscript, ctx.workspace.uploads), ensure_ascii=False))
    answer = ctx.ai.ask("format_plan", PLAN_SYSTEM, prompt)
    if not answer:
        return None
    plan, provider = answer
    updated, changes, notes = apply_plan(plan, manuscript, spec)
    summary = "; ".join(changes[:8]) if changes else "kept the default layout"
    ctx.log(STEP, f"Formatter agent ({provider}) layout plan: {summary}.", "success")
    ctx.ai.record(STEP, "ai", f"Layout plan: {summary}.", provider)
    return updated, [f"Formatter agent ({provider}): {n}" for n in notes]


def run(ctx: StepContext, manuscript: ManuscriptStructure, spec: VenueSpec) -> tuple[LaTeXProject, list[str]]:
    agent_notes: list[str] = []
    ai = ctx.ai
    if ai is not None and ai.full:
        ctx.log(STEP, "Formatter agent is planning the layout for this venue.")
        planned = _plan_step(ctx, manuscript, spec) if ai.can_ask else None
        if planned is None:
            ai.fallback(STEP)
            ctx.log(STEP, "No AI answer; using the default layout rules.", "warning")
        else:
            manuscript, agent_notes = planned
    elif ai is not None:
        ai.record(STEP, "rules", "Layout chosen by the template rules.")
    ctx.log(STEP, f"Rendering {spec.template.main_template} with {spec.template.document_class}.cls")
    formatter = Formatter(manuscript, spec, ctx.settings.templates_dir, ctx.workspace.uploads, ctx.workspace.work)
    project = formatter.build()
    formatter.notes.extend(agent_notes)
    for note in formatter.notes:
        ctx.log(STEP, note, "warning")
    for change in project.changes:
        ctx.log(STEP, f"Changed: {change}", "success")
    ctx.log(
        STEP,
        f"Wrote main.tex, {len(project.figure_files)} figure(s)"
        + (", references.bib" if project.bib_file else "")
        + (f"; {len(project.missing_figures)} figure file(s) missing" if project.missing_figures else ""),
        "success",
    )
    return project, formatter.notes
