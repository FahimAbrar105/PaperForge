"""Paper Forge Assistant: helps the author fix what the compliance report lists and Paper Forge could not fix.

It only advises: the author edits their own source and uploads it again. Without an AI provider it answers from
the check itself (its message and details, the venue's rule and a short how-to-fix text per check type). With
the user's Gemini key, or Ollama, it sends one AI request per question, grounded in the venue's rules, the issue,
an excerpt of the generated LaTeX and the last few turns. A suggested rewrite that changes the author's numbers
(their units or order), citations or the direction of a claim is left out. The conversation is kept in the job's
folder (final/chat.json), so it is deleted with the job.
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

from app.agents.venue_analyst import build_venue_spec
from app.models.venue import VenueSpec
from app.services.ai.base import AIError, AIProvider, AIRateLimited
from app.services.ai.router import build_providers, check_shape
from app.services.settings_store import UserSettings, redact
from app.services.venue_registry import VenueRegistry
from app.services.workspace import JobWorkspace

MAX_QUESTION_CHARS = 2000
MAX_MESSAGES = 200  # older messages are dropped from chat.json
HISTORY_MESSAGES = 6  # recent messages sent to the AI with a question
MAX_DETAILS = 8
LINES_BEFORE, LINES_AFTER = 6, 12  # lines kept around the place an issue points to
MAX_EXCERPT_CHARS = 2500
MAX_ANSWER_CHARS = 4000
REPORT_LISTS = ("failed", "warnings", "style", "manual_review")
KIND_LABEL = {"failed": "Failed", "warning": "Warning", "style": "Style suggestion", "manual_review": "Manual review"}

HOW_TO_FIX = {
    "compile_success": "Read the LaTeX error and the line it names. The usual causes are a command from a package "
                       "or .sty file you did not upload, a typo in a command, or an unbalanced brace. Fix it in your "
                       "source (you can try the fix in Overleaf with the LaTeX ZIP first) and upload again.",
    "page_limit": "Shorten the main text: tighten the wording, shrink or combine figures and tables, and move details "
                  "to an appendix if the venue allows one. Paper Forge never deletes content to make a paper fit. "
                  "Check the call for papers for extra pages (often with a fee).",
    "paper_size": "The venue's template sets the paper size. Remove anything in your source that changes it, such "
                  "as the geometry package, an a4paper option or \\pdfpagewidth, and upload again.",
    "fonts_embedded": "Fonts that are not embedded usually come from PDF figures. Export those figures again with "
                      "fonts embedded (in most tools: Save as PDF with font embedding on), or as high-resolution PNG.",
    "document_class": "Paper Forge uses the venue's own class and options. Remove your own \\documentclass options or "
                      "class files that override it, and do not upload a modified copy of the venue's class.",
    "forbidden_packages": "Remove the packages named above from your source: the venue does not allow packages that "
                          "change its margins, spacing, fonts or headings. Keep the template's defaults instead.",
    "required_sections": "Add the missing section with the heading the venue expects (for example Introduction or "
                         "Conclusion). If your paper has it under another name, rename the heading.",
    "abstract_length": "Bring the abstract within the word limit: keep the problem, the approach and the main "
                       "result, and cut background and detail. If no abstract was found, mark it clearly: an abstract "
                       "environment in LaTeX, 'abstract:' in Markdown front matter, or an 'Abstract' heading in Word.",
    "keywords_present": "Add keywords after the abstract: \\begin{IEEEkeywords}...\\end{IEEEkeywords} or "
                        "\\keywords{...} in LaTeX, 'keywords:' in Markdown front matter, or a 'Keywords:' (or "
                        "'Index Terms') paragraph in Word. Stay within the venue's maximum.",
    "figures_resolved": "Upload each missing figure file with the name your paper uses (folder names do not matter), "
                        "or convert EPS figures to PDF or PNG first. Until then each one is a placeholder box.",
    "citations_resolved": "Add a bibliography entry with exactly this key to your .bib file, or correct the key if it "
                          "is a typo. Paper Forge removed these citations from the PDF; they come back once the entry "
                          "exists.",
    "references_resolved": "Each label above is referenced but never defined. Add the label to its figure, table, "
                           "section or equation (\\label{...} in LaTeX, {#fig:...} in Markdown), or correct the name.",
    "overfull_boxes": "A line sticks into the margin, usually because of a long URL, a long word, inline math or a "
                      "wide table. Rephrase, put links in \\url{}, add hyphenation hints (\\-), or make the table "
                      "narrower (fewer columns, abbreviations, \\small).",
    "missing_glyphs": "The font cannot print these characters. Replace each one with its LaTeX command (for example "
                      "\\textrightarrow, $\\alpha$ or \\'{e}) or with plain text.",
    "bibliography_present": "Upload your .bib file together with the manuscript, or add a References section with "
                            "the entries.",
    "anonymity": "This version is reviewed double-blind: remove author names from the text and acknowledgments, and "
                 "cite your own earlier work in the third person ('Smith et al. [3] showed', not 'our earlier work "
                 "[3]').",
    "manual": "This is one of the venue's reminders, not a problem Paper Forge found: check it yourself against the "
              "venue's author kit and call for papers before you submit.",
    "lone_subsection": "Add a second subheading under that heading, or remove the single subheading and merge its "
                       "text into the section above.",
    "citation_as_noun": "Do not use a citation number as a word: write 'Smith et al. [3] show' or 'as shown in [3]' "
                        "instead of '[3] shows'.",
    "reference_details": "Complete the BibTeX entries listed: give conference papers an address (City, Country) and "
                         "a month, and replace 'and others' with the full author list.",
    "undefined_abbreviations": "At the first use of each abbreviation, write the full term followed by the "
                               "abbreviation in parentheses, for example 'graphics processing unit (GPU)'.",
    "stray_underscores": "A plain underscore prints as an underscore. For a subscript write math (P4$_{16}$); for "
                         "code or file names use \\texttt{}; otherwise replace it with a space or a hyphen.",
    "abstract_min_length": "The abstract is short for this venue. Say what the paper does, how, and what it finds, "
                           "in your own words; do not pad it.",
    "affiliation_location": "Write each affiliation as 'Dept. Name, University, City, Country'.",
    "spelling_consistency": "Choose British or American spelling and change the words listed so the whole paper "
                            "uses one.",
    "identifying_text": "In the anonymous version, cite your own earlier work in the third person ('Lee et al. [3] "
                        "showed', not 'our earlier work [3]'), link code only through an anonymous repository (or "
                        "not at all, if the venue says so), and leave grants and emails for the final version.",
    "figure_descriptions": "Add \\Description{...} inside each figure listed: one or two sentences saying what the "
                           "figure shows, for readers who cannot see it (not the caption again).",
    "ccs_concepts": "Choose your CCS concepts at https://dl.acm.org/ccs, then paste the CCSXML block and the "
                    "\\ccsdesc lines it generates into your source before \\maketitle.",
    "no_appendices": "Move the appendices listed into a separate supplementary file, so the main paper ends with the "
                     "references.",
    "abstract_form": "Rewrite the abstract in the form listed above (for example one paragraph, without citations, "
                     "footnotes, math or LaTeX commands): it is also copied as plain text.",
    "figure_resolution": "Export the images listed again at a higher resolution, or save plots and diagrams as "
                         "vector graphics (PDF), and upload them again.",
    "title_style": "Rewrite the title as the details say: title case for the main words, no all-capital words except "
                   "acronyms, and no math, footnotes or forced line breaks.",
    "heading_case": "Change the headings listed to the venue's capitalization, and avoid heading levels the venue "
                    "does not use.",
    "numbered_equations": "Number the equations listed: use the equation environment instead of equation*, \\[ \\] "
                          "or displaymath.",
    "typed_references": "A typed number such as \"Fig. 3\" points at a figure or table the paper does not have, or "
                        "a figure or table has no caption. Check the number in your text, and give every figure and "
                        "table a caption. In LaTeX, \\label each one and write Fig.~\\ref{...}, so numbers stay right "
                        "when things move.",
    "text_pattern": "This rule comes from the venue's guidelines: the message says what it asks for and the details "
                    "quote each place in your paper. Change those places in your own source.",
}
GENERIC_FIX = ("Find the place in your source that the message and details point to, change it there, and upload "
               "the paper again to check.")
# Manual-review items that are not the venue's reminders but something Paper Forge noticed in this paper.
NOTICED_FIX = (
    (r"No abstract", "Mark your abstract so Paper Forge finds it: an abstract environment in LaTeX, 'abstract:' in "
                     "Markdown front matter, or an 'Abstract' heading in Word. Until then the PDF has a placeholder "
                     "sentence instead of your abstract."),
    (r"No title", "Mark your title: \\title{...} in LaTeX, a '# Title' line or 'title:' front matter in Markdown, or "
                  "the Title style in Word. Until then the PDF says 'Untitled Paper'."),
    (r"No authors", "Add the authors: \\author{...} in LaTeX, 'author:' front matter in Markdown, or the lines under "
                    "the title in Word. Until then the PDF has a placeholder author block."),
    (r"No headings", "In Word, give each section heading the 'Heading 1' style and each subsection 'Heading 2', then "
                     "upload the paper again."),
    (r"Your references are a typed list", "Export your references as a .bib file (Zotero, Mendeley, JabRef and Google "
                                          "Scholar all can), upload it with the paper and cite with \\cite{key} or "
                                          "[@key]; then the citations follow the venue's style."),
    (r"(Content|Formatter) agent \(|Structure \(title", "This note comes from an AI agent that checked your paper: it "
                                                        "is advice, not a rule check. Look at the place it names in "
                                                        "your source and change it there if the note is right."),
)
NOTICED_GENERIC = ("Paper Forge noticed this while reading or formatting your paper. Check the place it names in your "
                   "source, fix it there, and upload the paper again.")
SOURCE_FORMATS = {
    "tex": ("a LaTeX file", "Write suggested_text in LaTeX."),
    "md": ("a Markdown file", "Write suggested_text in Markdown (LaTeX only inside $...$ math)."),
    "docx": ("a Word document", "Write suggested_text as plain text the author can paste into Word: no LaTeX "
                                "commands and no Markdown."),
}
PRIVACY = {
    None: "Answers come from Paper Forge's own rules, so nothing leaves this computer. Add a free Gemini key in "
          "Settings to ask in your own words.",
    "gemini": "Nothing is sent until you ask, whatever the agentic mode; then your question, the issue and a short "
              "excerpt of your paper go to Google's Gemini API with your key.",
    "ollama": "Your questions go to your local Ollama model; nothing leaves this computer.",
}

SYSTEM = (
    "You are the Paper Forge Assistant. Paper Forge formatted the author's paper for a venue and listed the "
    "problems it could not fix itself. You help the author fix them in their own source and follow the venue's "
    "guidelines. You only advise: you never edit the paper. Never change the author's claims, numbers, results or "
    "references: do not add, remove or alter any number, result, citation or bibliography entry, and never invent "
    "content. Base the answer on the venue rules, the issue and the excerpt given; when they do not answer the "
    "question, say so. Be concrete and brief. Return only JSON."
)
PROMPT = """Venue: {venue}
Venue rules (JSON): {rules}

Open issues in this paper's compliance report:
{issues}

{focus}

Excerpt of the LaTeX that Paper Forge generated (the author's own source is {source}):
<<<
{excerpt}
>>>

Recent conversation:
{history}

The author asks: {question}

{write_as}
Return JSON: {{"answer": "<plain text, no Markdown: what is wrong and the concrete steps to fix it in the author's own
source, at most about 150 words>", "suggested_text": "<text the author can paste into their source, or null>",
"original_text": "<the exact passage of the excerpt that suggested_text replaces, or null for new text>"}}"""

LINE_RE = re.compile(r"\bline\s+(\d+)")
QUOTED_RE = re.compile(r"\"([^\"]{2,80})\"|'([^']{1,40})'")
TOKEN_RE = re.compile(r"[\w:./-]*[A-Za-z][\w:./-]*")
HEADING_RE = re.compile(r"\\(?:sub)*section\*?\{([^{}]*)\}")
BIB_ENTRY_RE = re.compile(r"@\w+\s*\{\s*([^,\s{}]+)\s*,")
# A number and its unit, if any: 31\%, 2.5 ms, 4GB, 10x.
NUMBER_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(\\?%|\\times\b|×|(?<=\d)[A-Za-z]+\b|"
                       r"(?:ms|s|us|µs|ns|min|h|[KMGT]B|[KMG]bps|[kMG]?Hz|[mk]?W|mm|cm|km|kg|fps|dB|x)\b)?")
UNIT_NAMES = {"\\%": "%", "\\times": "x", "×": "x"}
# Lengths, widths and scales in LaTeX layout commands are page layout, not the author's numbers.
LAYOUT_RE = re.compile(r"\[[^\[\]]*=[^\[\]]*\]"
                       r"|\\(?:setlength|addtolength|vspace|hspace|resizebox|scalebox|rule)\*?(?:\s*\{[^{}]*\})+"
                       r"|\\renewcommand\s*\{\\arraystretch\}\s*\{[^{}]*\}"
                       r"|\d*\.?\d+\s*\\(?:columnwidth|linewidth|textwidth|textheight|hsize|baselineskip)\b")
SENTENCE_BREAK_RE = re.compile(r"(?<=[.!?])\s+|\n+")
REWRITE_LIKENESS = 0.5  # how alike a suggestion and a sentence must be to count as a rewrite of it
# Words whose swap turns a claim around ("reduces" -> "increases"), by word stem.
OPPOSITES = (("reduc", "increas"), ("decreas", "increas"), ("improv", "degrad"), ("improv", "worsen"),
             ("outperform", "underperform"), ("higher", "lower"), ("faster", "slower"), ("better", "worse"))
CITE_RE = re.compile(r"\\[A-Za-z]*cite[A-Za-z]*\*?\s*(?:\[[^\]]*\]\s*)*\{([^{}]*)\}")
PANDOC_CITE_RE = re.compile(r"(?<![\w.])@(\w(?:[\w:.\-/]*\w)?)")
# Where in the generated LaTeX an issue of this type is, when its message does not say.
EXCERPT_REGION = {
    "abstract_length": "front", "abstract_min_length": "front", "keywords_present": "front",
    "document_class": "preamble", "forbidden_packages": "preamble", "paper_size": "preamble",
    "fonts_embedded": "figures", "required_sections": "outline", "affiliation_location": "authors",
    "reference_details": "bib", "citations_resolved": "bib", "bibliography_present": "bib",
    "abstract_form": "front", "title_style": "authors", "ccs_concepts": "authors", "figure_resolution": "figures",
}
QUESTION_REGION = {
    "abstract": "front", "keyword": "front", "index term": "front", "title": "authors", "author": "authors",
    "affiliation": "authors", "package": "preamble", "preamble": "preamble", "figure": "figures",
    "bibliograph": "bib", "reference": "bib", "citation": "bib",
}

_chat_lock = threading.Lock()
_times_cleared: dict[Path, int] = {}  # per chat file, since Paper Forge started


@dataclass
class Issue:
    id: str
    type: str
    status: str
    message: str
    details: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return KIND_LABEL.get(self.status, self.status)

    def public(self) -> dict:
        return {"id": self.id, "type": self.type, "status": self.status, "label": self.label,
                "message": self.message, "details": self.details}


@dataclass
class JobPaper:
    """What the assistant knows about one finished job."""

    venue_name: str
    spec: VenueSpec | None
    issues: list[Issue]
    tex: str
    bib: str
    chat_path: Path
    source_format: str = "tex"  # the author's own source: tex, md or docx

    def issue(self, issue_id: str) -> Issue | None:
        return next((i for i in self.issues if i.id == issue_id), None)


# ---------------------------------------------------------------------- loading
def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def open_issues(report: dict) -> list[Issue]:
    """Failed checks, warnings, style suggestions and manual-review items; not passed checks or changes made."""
    issues: list[Issue] = []
    for key in REPORT_LISTS:
        items = report.get(key)
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            issue_id = str(item.get("check_id") or key)
            if any(i.id == issue_id for i in issues):
                issue_id = f"{issue_id}_{len(issues) + 1}"
            details = item.get("details")
            issues.append(Issue(id=issue_id, type=str(item.get("type", "")), status=str(item.get("status", key)),
                                message=str(item.get("message", "")),
                                details=[str(d) for d in details] if isinstance(details, list) else []))
    return issues


def load_spec(ws: JobWorkspace, registry: VenueRegistry, venue_id: str) -> VenueSpec | None:
    """The venue spec the job used (written by the Venue Analyst), else the venue's current rules."""
    try:
        return VenueSpec.model_validate_json((ws.root / "venue_spec.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    try:
        return build_venue_spec(registry.load_rules(venue_id), registry.templates_dir)
    except (KeyError, OSError, ValueError):
        return None


def source_format(ws: JobWorkspace) -> str:
    """tex, md or docx: the format of the author's own source, as the Content Structurer saw it."""
    try:
        fmt = json.loads((ws.root / "manuscript.json").read_text(encoding="utf-8"))["source"]["format"]
    except (OSError, ValueError, KeyError, TypeError):
        return "tex"
    return fmt if fmt in SOURCE_FORMATS else "tex"


def load_paper(ws: JobWorkspace, registry: VenueRegistry, venue_id: str) -> JobPaper | None:
    """None when the job has no compliance report."""
    try:
        report = json.loads((ws.final / "compliance_report.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(report, dict):
        return None
    spec = load_spec(ws, registry, venue_id)
    tex_files = [ws.work / "main.tex", *sorted((ws.work / "sections").glob("*.tex"))]
    return JobPaper(venue_name=str(report.get("venue_name") or (spec.display_name if spec else venue_id)),
                    spec=spec, issues=open_issues(report), tex="\n".join(_read(p) for p in tex_files),
                    bib=_read(ws.work / "references.bib"), chat_path=ws.final / "chat.json",
                    source_format=source_format(ws))


# ------------------------------------------------------------ rule-based answers
def venue_rule(spec: VenueSpec | None, issue: Issue) -> str:
    check = next((c for c in spec.checks if c.id == issue.id), None) if spec else None
    return check.description if check else ""


def is_venue_reminder(issue: Issue, spec: VenueSpec | None) -> bool:
    """The venue's own manual checks and reminders, as opposed to what Paper Forge noticed in this paper."""
    return not issue.id.startswith("manual_note") or bool(spec and issue.message in spec.manual_review_items)


def how_to_fix(issue: Issue, spec: VenueSpec | None = None) -> str:
    if issue.type != "manual" or is_venue_reminder(issue, spec):
        return HOW_TO_FIX.get(issue.type, GENERIC_FIX)
    return next((fix for pattern, fix in NOTICED_FIX if re.match(pattern, issue.message)), NOTICED_GENERIC)


def rule_answer(paper: JobPaper, issue: Issue) -> str:
    lines = [f"{issue.label}: {issue.message}"]
    lines += [f"- {d}" for d in issue.details[:MAX_DETAILS]]
    if len(issue.details) > MAX_DETAILS:
        lines.append(f"- ...and {len(issue.details) - MAX_DETAILS} more in the report.")
    rule = venue_rule(paper.spec, issue)
    if rule and rule != issue.message:
        lines.append(f"Venue rule for {paper.venue_name}: {rule.rstrip('.')}.")
    lines.append(f"How to fix: {how_to_fix(issue, paper.spec)}")
    if issue.status != "manual_review":
        lines.append("Paper Forge does not change your text for this: fix it in your own source and upload the paper "
                     "again to check.")
    return "\n".join(lines)


def offline_answer(paper: JobPaper, ai_failed: bool = False) -> str:
    """The answer to a free-text question when no AI can answer it."""
    if ai_failed:
        lines = ["I could not get an AI answer to this question, so here is what the report says."]
    else:
        lines = [("I can answer questions in your own words only with an AI key. Without one, I explain each issue "
                  "from Paper Forge's own rules: press \"Help me fix this\" next to it to see what is wrong, what the "
                  "venue asks for and how to fix it in your source.")]
    if paper.issues:
        lines += ["", f"Open issues in this paper ({len(paper.issues)}):"]
        lines += [f"{n}. {i.label}: {i.message}" for n, i in enumerate(paper.issues, 1)]
    else:
        lines += ["", "This paper has no open issues: every check passed."]
    if not ai_failed:
        lines += ["", ("To ask questions in your own words, add a free Gemini API key in Settings (get one at "
                       "aistudio.google.com/apikey), or choose Ollama there.")]
    return "\n".join(lines)


# --------------------------------------------------------------------- excerpts
def _around(tex: str, index: int) -> str:
    lines = tex.splitlines()
    if not 0 <= index < len(lines):
        return ""
    return "\n".join(lines[max(0, index - LINES_BEFORE): index + LINES_AFTER + 1])


def _outline(tex: str) -> str:
    return "\n".join(line.strip() for line in tex.splitlines() if HEADING_RE.search(line))


def _bib_entries(bib: str, text: str | None) -> str:
    """The .bib entries whose keys the text names; every entry when text is None."""
    starts = list(BIB_ENTRY_RE.finditer(bib))
    entries = []
    for n, m in enumerate(starts):
        if text is None or re.search(rf"(?<![\w:.-]){re.escape(m.group(1))}(?![\w-]|:\w)", text):
            entries.append(bib[m.start(): starts[n + 1].start() if n + 1 < len(starts) else len(bib)].strip())
    return "\n\n".join(entries)


def _region(paper: JobPaper, region: str, text: str | None = None) -> str:
    tex = paper.tex
    if region == "front":
        start = next((i for i in (tex.find("\\begin{abstract}"), tex.find("\\maketitle")) if i >= 0), -1)
        end = tex.find("\\section", start + 1)
        return tex[start: end if end > start else len(tex)] if start >= 0 else ""
    if region == "preamble":
        return "\n".join(line for line in tex.splitlines()
                         if re.match(r"\s*\\(documentclass|usepackage|RequirePackage)\b", line))
    if region == "authors":
        start, end = tex.find("\\title"), tex.find("\\maketitle")
        return tex[start:end] if 0 <= start < end else ""
    if region == "figures":
        return "\n".join(line for line in tex.splitlines() if "\\includegraphics" in line)
    if region == "bib":
        return _bib_entries(paper.bib, text)
    if region == "outline":
        return _outline(tex)
    return ""


def _candidates(issue: Issue) -> list[str]:
    """What the issue quotes or lists, most specific first: phrases, listed items, details, then keys and names."""
    texts = [issue.message, *issue.details]
    quoted = [q.removesuffix("...") for t in texts for pair in QUOTED_RE.findall(t) for q in pair if q]
    others = []
    for t in texts:
        listed = t.split(": ", 1)[1].split(". ", 1)[0] if ": " in t else ""
        others += [re.sub(r"\s*\(.*?\)", "", item).strip(" .") for item in re.split(r",\s*|\s+and\s+", listed)]
    others += issue.details
    tokens = [tok.strip(":.,;") for d in issue.details for tok in TOKEN_RE.findall(d)]
    others += [tok for tok in tokens if re.search(r"[\d_:.]", tok)]
    return list(dict.fromkeys([*quoted, *(o for o in others if len(o) >= 3)]))


def _search(tex: str, candidates: list[str]) -> str:
    """The lines around the first place the generated LaTeX contains one of the candidates (exact case first)."""
    lines = tex.splitlines()
    for flags in (0, re.I):
        for candidate in candidates:
            for needle in dict.fromkeys([candidate, candidate.replace("_", "\\_")]):
                pattern = re.compile(rf"(?<!\w){re.escape(needle)}(?!\w)", flags)
                for n, line in enumerate(lines):
                    if not line.lstrip().startswith("%") and pattern.search(line):
                        return _around(tex, n)
    return ""


def _question_region(paper: JobPaper, question: str) -> str:
    asked = question.lower()
    lines = paper.tex.splitlines()
    for n, line in enumerate(lines):
        heading = HEADING_RE.search(line)
        if heading and len(heading.group(1).strip()) >= 4 and heading.group(1).strip().lower() in asked:
            return "\n".join(lines[n: n + LINES_BEFORE + LINES_AFTER + 1])
    for word, region in QUESTION_REGION.items():
        if word in asked:
            return _region(paper, region)
    return ""


def find_excerpt(paper: JobPaper, issue: Issue | None, question: str = "") -> str:
    """The part of the generated LaTeX an issue or question is about, kept short; else the paper's headings."""
    if issue is None:
        found = _question_region(paper, question)
    else:
        text = " ".join([issue.message, *issue.details])
        line = LINE_RE.search(text)
        found = _around(paper.tex, int(line.group(1)) - 1) if line else ""
        if not found and issue.type in EXCERPT_REGION:
            found = _region(paper, EXCERPT_REGION[issue.type], text)
        found = found or _search(paper.tex, _candidates(issue))
    return (found or _outline(paper.tex)).strip()[:MAX_EXCERPT_CHARS]


# ------------------------------------------------------------------------ guard
def _numbers(text: str) -> list[tuple[str, str]]:
    """The numbers of a text with their units, in order: [("31", "%"), ("3", "")]. Not counted: the digits of
    citation keys such as lane2015early, and the lengths and scales of LaTeX layout commands."""
    text = LAYOUT_RE.sub(" ", text)
    for key in sorted(citation_keys(text), key=len, reverse=True):
        text = text.replace(key, " ")
    return [(number, UNIT_NAMES.get(unit, unit)) for number, unit in NUMBER_RE.findall(text)]


def citation_keys(text: str) -> set[str]:
    """Citation keys in LaTeX (\\cite{a,b}), Markdown ([@a; @b]) and BibTeX entries (@article{a,)."""
    keys = {k.strip() for group in CITE_RE.findall(text) for k in group.split(",") if k.strip()}
    keys |= set(BIB_ENTRY_RE.findall(text))
    return keys | set(PANDOC_CITE_RE.findall(BIB_ENTRY_RE.sub(" ", text)))


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in SENTENCE_BREAK_RE.split(text) if part.strip()]


def closest_passage(suggested: str, texts: list[str]) -> tuple[str, float]:
    """The run of consecutive sentences, in one of the texts, most like the suggestion, and how alike (0 to 1)."""
    matcher = SequenceMatcher(None, autojunk=False)
    matcher.set_seq2(re.findall(r"[a-z0-9]+", suggested.lower()))
    width = min(len(_sentences(suggested)), 5) + 1
    best, likeness = "", 0.0
    for text in texts:
        sentences = _sentences(text)
        for i in range(len(sentences)):
            for j in range(i + 1, min(len(sentences), i + width) + 1):
                passage = " ".join(sentences[i:j])
                matcher.set_seq1(re.findall(r"[a-z0-9]+", passage.lower()))
                if matcher.quick_ratio() > likeness and matcher.ratio() > likeness:
                    best, likeness = passage, matcher.ratio()
    return best, likeness


def _turned_around(passage: str, suggested: str) -> str:
    """'"reduces" into "increases"' when the rewrite swaps a word for its opposite, else ""."""
    def words(text: str, stem: str) -> list[str]:
        return re.findall(rf"\b{stem}\w*", text, re.I)

    for a, b in OPPOSITES:
        for old, new in ((a, b), (b, a)):
            if (len(words(suggested, old)) < len(words(passage, old))
                    and len(words(suggested, new)) > len(words(passage, new))):
                return f'"{words(passage, old)[0]}" into "{words(suggested, new)[0]}"'
    return ""


def check_suggestion(suggested: str, original: str, excerpt: str, question: str = "") -> str:
    """Why a suggested rewrite must be left out, or "" when it keeps the author's claims.

    The rewrite is compared with the passage it replaces: the one the AI named when the excerpt has it, else the
    sentences of the excerpt (or of the author's question) most like the rewrite. It must keep that passage's
    citations and its numbers with their units, in the same order, and must not swap a word for its opposite.
    Numbers in the author's own question are theirs to change. New text that is like no sentence and has no numbers
    or citations changes nothing of the author's."""
    found = bool(original) and " ".join(original.split()) in " ".join(excerpt.split())
    passage, likeness = (original, 1.0) if found else closest_passage(suggested, [excerpt, question])
    if not original and likeness < REWRITE_LIKENESS and not _numbers(suggested) and not citation_keys(suggested):
        return ""
    trusted = {number for number, _ in _numbers(question)}
    before = [f"{n}{unit}" for n, unit in _numbers(passage) if n not in trusted]
    after = [f"{n}{unit}" for n, unit in _numbers(suggested) if n not in trusted]
    added = sorted({n for n, _ in _numbers(suggested)} - {n for n, _ in _numbers(passage)} - trusted)
    if added:
        return f"it adds the number(s) {', '.join(added)}, which your text does not have"
    new_keys = sorted(citation_keys(suggested) - citation_keys(f"{passage}\n{question}"))
    if new_keys:
        return f"it cites {', '.join(new_keys)}, which your text does not cite there"
    dropped = sorted(k for k in citation_keys(passage) if k not in suggested)
    if dropped:
        return f"it drops the citation(s) {', '.join(dropped)}"
    if changed := list((Counter(after) - Counter(before)).elements()):
        return f"it changes a number or its unit ({', '.join(changed)}, where your text has {', '.join(before)})"
    if missing := list((Counter(before) - Counter(after)).elements()):
        return f"it drops the number(s) {', '.join(missing)}"
    if after != before:
        return f"it changes the order of the numbers (your text has {', '.join(before)})"
    if swapped := _turned_around(passage, suggested):
        return f"it turns {swapped}, which changes what your text claims"
    return ""


# ---------------------------------------------------------------------- answers
def ai_provider(settings: UserSettings) -> AIProvider | None:
    """The user's AI provider for the assistant (their Gemini key, or Ollama when chosen in Settings), or None.
    The assistant uses it whatever the default agentic mode is; it is separate from the jobs' request budgets."""
    providers = build_providers(settings, "full")
    return providers[0] if providers else None


def privacy_line(provider: AIProvider | None) -> str:
    return PRIVACY.get(provider.name if provider else None, PRIVACY["gemini"])


def venue_rules(spec: VenueSpec | None) -> dict:
    if spec is None:
        return {}
    return {"layout": spec.layout.model_dump(), "content_rules": spec.content_rules.model_dump(),
            "checks": [c.description for c in spec.checks], "reminders": spec.manual_review_items}


def build_prompt(paper: JobPaper, question: str, issue: Issue | None, excerpt: str, history: list[dict]) -> str:
    if issue:
        focus = (f"The author asks about this issue (JSON): {json.dumps(issue.public(), ensure_ascii=False)}\n"
                 f"Paper Forge's own advice for this kind of issue: {how_to_fix(issue, paper.spec)}")
    else:
        focus = "The question is not about one issue in particular."
    turns = "\n".join(f"{'Author' if m.get('role') == 'user' else 'Assistant'}: {str(m.get('text', ''))[:500]}"
                      for m in history[-HISTORY_MESSAGES:])
    source, write_as = SOURCE_FORMATS[paper.source_format]
    return PROMPT.format(venue=paper.venue_name, rules=json.dumps(venue_rules(paper.spec), ensure_ascii=False),
                         issues="\n".join(f"- {i.label}: {i.message}" for i in paper.issues[:30]) or "(none)",
                         focus=focus, source=source, excerpt=excerpt or "(not available)", history=turns or "(none)",
                         question=question or "How do I fix this issue?", write_as=write_as)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def user_message(question: str, issue: Issue | None) -> dict:
    text = question or f"Help me fix this: {issue.message if issue else ''}"
    return {"role": "user", "text": text, "issue_id": issue.id if issue else None, "at": _now()}


def _answer(text: str, issue: Issue | None, source: str = "rules", model: str = "", suggested_text: str | None = None,
            note: str = "") -> dict:
    return {"role": "assistant", "text": text, "source": source, "model": model, "suggested_text": suggested_text,
            "note": note, "issue_id": issue.id if issue else None, "at": _now()}


def _text(value: object, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def reply(paper: JobPaper, question: str, issue: Issue | None, history: list[dict], settings: UserSettings) -> dict:
    """The assistant's answer to one message, as a chat message. Uses at most one AI request."""
    provider = ai_provider(settings)
    if provider is None:
        return _answer(offline_answer(paper) if question or issue is None else rule_answer(paper, issue), issue)
    built_in = rule_answer(paper, issue) if issue else offline_answer(paper, ai_failed=True)
    excerpt = find_excerpt(paper, issue, question)
    try:
        answer = provider.generate_json(SYSTEM, build_prompt(paper, question, issue, excerpt, history))
        check_shape("assistant", answer)
    except Exception as exc:  # whatever went wrong, the author gets the built-in answer
        why = redact(str(exc), settings) if isinstance(exc, AIError) else f"unexpected error {exc.__class__.__name__}"
        later = ""
        if isinstance(exc, AIRateLimited):
            later = " Try again tomorrow." if exc.daily else " Try again in a minute."
        return _answer(built_in, issue, note=f"The AI could not answer ({why}), so this is Paper Forge's built-in "
                                             f"answer.{later}")
    text = redact(_text(answer.get("answer"), MAX_ANSWER_CHARS), settings)
    if not text:
        return _answer(built_in, issue, note="The AI gave an empty answer, so this is Paper Forge's built-in answer.")
    suggested = redact(_text(answer.get("suggested_text"), MAX_ANSWER_CHARS), settings)
    note = ""
    if suggested.lower() in {"", "null", "none"}:
        suggested = ""
    elif why := check_suggestion(suggested, _text(answer.get("original_text"), MAX_ANSWER_CHARS), excerpt, question):
        suggested = ""
        note = (f"The suggested rewrite was left out because {why}: the assistant never changes your claims, "
                "numbers or references.")
    return _answer(text, issue, source=provider.name, model=provider.last_model, suggested_text=suggested or None,
                   note=note)


# ------------------------------------------------------------------------- chat
def load_chat(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    messages = data.get("messages") if isinstance(data, dict) else None
    return [m for m in messages if isinstance(m, dict)] if isinstance(messages, list) else []


def times_cleared(path: Path) -> int:
    return _times_cleared.get(path, 0)


def add_to_chat(path: Path, messages: list[dict], cleared: int | None = None) -> None:
    """Append messages to the chat. ``cleared`` is times_cleared() from before the answer was written: when the
    author cleared the chat since, the answer is not saved, so the cleared exchange does not come back."""
    with _chat_lock:
        if (cleared is not None and times_cleared(path) != cleared) or not path.parent.is_dir():
            return  # cleared, or the job deleted, while the assistant was answering
        chat = [*load_chat(path), *messages][-MAX_MESSAGES:]
        tmp = path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps({"messages": chat}, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, path)
        except FileNotFoundError:  # the job is being deleted right now
            pass


def clear_chat(path: Path) -> None:
    with _chat_lock:
        path.unlink(missing_ok=True)
        _times_cleared[path] = times_cleared(path) + 1
