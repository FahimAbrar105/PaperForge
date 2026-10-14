"""Step 3 - Content Structurer: uploads -> ManuscriptStructure.

The rule-based parser always runs first and produces a draft structure.

- Full agentic mode: an AI agent reviews that draft against the source text and
  corrects the front matter (title, authors, affiliations, abstract, keywords)
  and, for Word files, heading levels. A Word file the parser could not read
  well gets a full outline from the agent instead.
- Partial mode: the AI is asked only for a Word file the parser could not read well.
- Off, or when the AI limit is reached: the parser's draft is used as is.

Everything the agent returns is verified against the upload: text that does not
appear in the source is discarded, so the AI cannot invent content. Body text
always comes from the upload itself, never from the model.
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher

from app.agents.base import StepContext, StepError
from app.models.job import UploadedFile
from app.models.manuscript import Author, ManuscriptStructure, Section, TextBlock, flatten_sections, nest_sections
from app.parsers import dispatcher
from app.parsers.latex_parser import latex_to_plain, plain_title
from app.parsers.text_utils import latex_escape, normalize_space, strip_heading_number

STEP = "Content Structurer"
CONFIDENCE_THRESHOLD = 0.6
WORD_FILE_UNREADABLE = ("the file could not be read as a Word document. Open it in Word, save it again as .docx "
                        "(File > Save As), and upload it again.")

OUTLINE_SYSTEM = (
    "You extract the structure of a research paper from raw text. Copy text exactly as it appears; "
    "never paraphrase, summarize, translate, or add anything. If a field is not present, use an empty "
    "value. Return only JSON."
)
OUTLINE_PROMPT = """Return JSON with this shape:
{{"title": "...", "authors": [{{"name": "...", "affiliations": ["..."], "email": "..."}}],
 "abstract": "...", "keywords": ["..."],
 "headings": [{{"text": "exact heading line as it appears", "level": 1}}]}}
Rules: headings are section titles in reading order (level 1 = section, 2 = subsection). Exclude the
title, "Abstract", and figure/table captions. Include "References" if present.

PAPER TEXT:
<<<
{text}
>>>"""


REVIEW_SYSTEM = (
    "You are the Content Structurer agent of a paper-formatting pipeline. You check a parser's draft "
    "structure of a research paper against its source text. Copy text exactly as it appears in the source; "
    "never paraphrase, summarize, translate, or add anything. Return only JSON."
)
REVIEW_PROMPT = """A rule-based parser produced this draft structure of a paper (source format: {fmt}):
{draft}

Compare it with the source text below and return corrections as JSON:
{{"title": "<exact title if the draft's title is wrong or empty, else empty>",
 "authors": [{{"name": "...", "affiliations": ["..."], "email": "..."}}],
 "abstract": "<exact abstract if the draft's is wrong or empty, else empty>",
 "keywords": ["<exact keywords if the draft's are wrong or empty>"],
 "heading_levels": [{{"index": <heading index from the draft>, "level": <1, 2 or 3>}}],
 "notes": ["<short, concrete problem the author should check>"]}}
Rules: authors is the complete corrected author list, or [] if the draft's list is right. Only list
headings whose level is wrong. Notes are for problems you can point to in the source text (for example a
heading or author the draft is missing); do not count figures, tables or references, the pipeline checks those.
At most 5 notes; [] if there is nothing to report.

SOURCE TEXT:
<<<
{text}
>>>"""


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _items(answer: dict, key: str) -> list:
    """A list field of the agent's answer; anything else is ignored (a string would give one item per letter)."""
    value = answer.get(key)
    return value if isinstance(value, list) else []


def _appears(fragment: str, source_norm: str, min_ratio: float = 0.85) -> bool:
    frag = _norm(fragment)
    if not frag:
        return False
    if frag in source_norm:
        return True
    # Allow small extraction differences (hyphenation, ligatures) on short fragments: compare the fragment
    # with the source text at every place where its first word appears.
    if len(frag) < 400:
        first = frag.split()[0]
        idx = source_norm.find(first)
        while idx != -1:
            if SequenceMatcher(None, frag, source_norm[idx : idx + len(frag)]).ratio() >= min_ratio:
                return True
            idx = source_norm.find(first, idx + 1)
    return False


def _verified_authors(answer: list, source_text: str) -> list[Author]:
    """The agent's authors whose name appears in the source; affiliations and emails not in the source are dropped."""
    src = _norm(source_text)
    authors = []
    for a in answer or []:
        if not isinstance(a, dict) or not _appears(str(a.get("name", "")), src):
            continue
        affiliations = [normalize_space(str(x)) for x in a.get("affiliations") or [] if _appears(str(x), src)]
        email = str(a.get("email") or "").strip() or None
        if email and email.lower() not in source_text.lower():
            email = None
        authors.append(Author(name=normalize_space(str(a["name"])), affiliations=affiliations[:4], email=email))
    return authors


def _paragraphs(lines: list[str]) -> list[str]:
    """Group raw lines into paragraphs (blank lines, or short lines ending a sentence)."""
    paras: list[str] = []
    buf: list[str] = []
    lengths = sorted(len(l) for l in lines if l.strip()) or [80]
    median = lengths[len(lengths) // 2]
    for line in lines:
        s = line.strip()
        if not s:
            if buf:
                paras.append(" ".join(buf))
                buf = []
            continue
        buf.append(s)
        if s.endswith((".", ":", "?", "!")) and len(s) < 0.6 * median:
            paras.append(" ".join(buf))
            buf = []
    if buf:
        paras.append(" ".join(buf))
    return [re.sub(r"(\w)- (\w)", r"\1\2", p) for p in paras if p.strip()]


def apply_outline(outline: dict, plain_text: str, base: ManuscriptStructure, provider: str) -> ManuscriptStructure | None:
    """Rebuild the manuscript from verified outline + the upload's own text. None if unusable."""
    source_norm = _norm(plain_text)
    lines = plain_text.splitlines()
    norm_lines = [_norm(l) for l in lines]

    title = str(outline.get("title") or "").strip()
    if title and not _appears(title, source_norm):
        title = ""
    abstract = str(outline.get("abstract") or "").strip()
    if abstract and not _appears(abstract[:300], source_norm):
        abstract = ""
    keywords = [str(k).strip() for k in _items(outline, "keywords") if _appears(str(k), source_norm)]
    authors = _verified_authors(_items(outline, "authors"), plain_text)

    # Locate headings as whole lines in the source, in order.
    positions: list[tuple[int, str, int]] = []
    cursor = 0
    for h in _items(outline, "headings"):
        if not isinstance(h, dict):
            continue
        text = normalize_space(str(h.get("text", "")))
        target = _norm(text)
        if not target:
            continue
        for idx in range(cursor, len(norm_lines)):
            if norm_lines[idx] == target:
                level = h.get("level", 1)
                level = level if isinstance(level, int) and 1 <= level <= 4 else 1
                positions.append((idx, text, level))
                cursor = idx + 1
                break
    if len(positions) < 2:
        return None

    flat: list[Section] = []  # sections in reading order
    for n, (idx, text, level) in enumerate(positions):
        end = positions[n + 1][0] if n + 1 < len(positions) else len(lines)
        title_clean = strip_heading_number(text)
        if _norm(title_clean) in {"references", "bibliography"}:
            break
        if _norm(title_clean).startswith("acknowledg"):
            continue
        body = _paragraphs(lines[idx + 1 : end])
        if n == 0 and abstract:
            body = [p for p in body if not _appears(p[:200], _norm(abstract))]
        flat.append(Section(title=latex_escape(title_clean), level=level,
                            blocks=[TextBlock(kind="paragraph", content=latex_escape(p), format="latex") for p in body]))
    if not flat:
        return None

    # Re-attach figures/tables found deterministically.
    for fig in base.figures:
        target = next((s for s in flat if fig.caption and any(_norm(fig.caption)[:40] in _norm(b.content) for b in s.blocks)), None)
        (target or flat[-1]).blocks.append(TextBlock(kind="figure_ref", content=fig.id))
    for tab in base.tables:
        flat[-1].blocks.append(TextBlock(kind="table_ref", content=tab.id))

    result = base.model_copy(deep=True)
    result.title = latex_escape(title) if title else base.title
    result.abstract = latex_escape(abstract) if abstract else base.abstract
    result.keywords = keywords or base.keywords
    result.authors = authors or base.authors
    result.sections = nest_sections(flat)
    result.text_format = "latex"
    result.source.parser = f"deterministic+{provider}"
    result.source.confidence = max(base.source.confidence, 0.75)
    result.source.warnings.append(f"Structure (title, headings, abstract) suggested by {provider} and verified against your text.")
    return result


def draft_summary(m: ManuscriptStructure) -> str:
    """Compact JSON view of the parser's draft for the review agent."""
    headings = [{"index": i, "title": normalize_space(s.title)[:120], "level": s.level}
                for i, s in enumerate(m.all_sections())]
    data = {
        "title": normalize_space(m.title)[:300],
        "authors": [{"name": a.name, "affiliations": a.affiliations[:3], "email": a.email} for a in m.authors[:20]],
        "abstract_start": normalize_space(m.abstract)[:400],
        "keywords": m.keywords[:15],
        "headings": headings[:80],
        "figures": len(m.figures), "tables": len(m.tables), "references": len(m.references),
    }
    return json.dumps(data, ensure_ascii=False)


def restructure(sections: list[Section], new_levels: dict[int, int]) -> list[Section]:
    """Change heading levels by flat index and rebuild the section tree."""
    flat = flatten_sections(sections)
    for i, section in enumerate(flat):
        section.subsections = []
        section.level = new_levels.get(i, section.level)
    return nest_sections(flat)


def _fill_author_details(authors: list[Author], proposed: list[Author]) -> bool:
    """Fill missing affiliations and emails from the agent's list, and add authors the parser missed.
    True when anything changed."""
    by_name = {_norm(a.name): a for a in proposed}
    changed = False
    for a in authors:
        p = by_name.get(_norm(a.name))
        if p and not a.affiliations and p.affiliations:
            a.affiliations = p.affiliations
            changed = True
        if p and not a.email and p.email:
            a.email = p.email
            changed = True
    known = {_norm(a.name) for a in authors}
    missing = [p for p in proposed if _norm(p.name) not in known]
    if missing and len(authors) < len(proposed):
        authors.extend(missing)
        changed = True
    return changed


def _as_text(value: str, m: ManuscriptStructure) -> str:
    """Agent answers are plain text; convert them to the manuscript's text format."""
    return latex_escape(value) if m.text_format == "latex" else value


def apply_review(review: dict, source_text: str, base: ManuscriptStructure, provider: str
                 ) -> tuple[ManuscriptStructure, list[str]]:
    """Apply the agent's verified corrections. Returns (manuscript, list of changes made)."""
    m = base.model_copy(deep=True)
    src = _norm(source_text)
    changes: list[str] = []

    title = normalize_space(str(review.get("title") or ""))
    if title and _appears(title, src) and _norm(title) != _norm(plain_title(m)):
        if not m.title or not _appears(plain_title(m), src):
            m.title = _as_text(title, m)
            changes.append("title")

    abstract = normalize_space(str(review.get("abstract") or ""))
    if abstract and _appears(abstract[:300], src) and (not m.abstract or not _appears(latex_to_plain(m.abstract)[:300], src)):
        m.abstract = _as_text(abstract, m)
        changes.append("abstract")

    keywords = [normalize_space(str(k)) for k in _items(review, "keywords") if str(k).strip()]
    keywords = [k for k in keywords if _appears(k, src)][:15]
    if keywords and not m.keywords:
        m.keywords = keywords
        changes.append("keywords")

    proposed = _verified_authors(_items(review, "authors"), source_text)
    if proposed and not m.authors:
        m.authors = proposed
        changes.append("authors")
    elif proposed and _fill_author_details(m.authors, proposed):
        changes.append("author details")

    if m.source.format == "docx":
        count = len(m.all_sections())
        levels: dict[int, int] = {}
        for h in _items(review, "heading_levels"):
            if not isinstance(h, dict):
                continue
            idx, level = h.get("index"), h.get("level")
            if isinstance(idx, int) and isinstance(level, int) and 0 <= idx < count and 1 <= level <= 3:
                levels[idx] = level
        if levels:
            m.sections = restructure(m.sections, levels)
            changes.append(f"{len(levels)} heading level(s)")

    for note in _items(review, "notes")[:5]:
        note = normalize_space(str(note))[:200]
        if note:
            m.source.warnings.append(f"Content agent ({provider}): {note}")
    if changes:
        m.source.parser = f"deterministic+{provider}"
    return m, changes


def _outline_step(ctx: StepContext, m: ManuscriptStructure, text: str) -> ManuscriptStructure | None:
    answer = ctx.ai.ask("structure_outline", OUTLINE_SYSTEM, OUTLINE_PROMPT.format(text=text))
    if not answer:
        return None
    improved = apply_outline(answer[0], text, m, answer[1])
    if improved:
        ctx.log(STEP, f"AI outline verified against the source: {len(improved.all_sections())} sections.", "success")
        ctx.ai.record(STEP, "ai", "Rebuilt the paper's outline (verified against your text).", answer[1])
        return improved
    ctx.log(STEP, "AI outline could not be verified against your text; kept the parser's result.", "warning")
    ctx.ai.reject(STEP, answer[1], "its outline could not be verified against your text")
    return m


def _review_step(ctx: StepContext, m: ManuscriptStructure, text: str) -> ManuscriptStructure | None:
    prompt = REVIEW_PROMPT.format(fmt=m.source.format, draft=draft_summary(m), text=text)
    answer = ctx.ai.ask("structure_review", REVIEW_SYSTEM, prompt)
    if not answer:
        return None
    reviewed, changes = apply_review(answer[0], text, m, answer[1])
    note = ("Corrected " + ", ".join(changes) + " (verified against your text)." if changes
            else "Checked the parser's structure; no corrections needed.")
    ctx.log(STEP, f"Content agent ({answer[1]}): {note}", "success")
    ctx.ai.record(STEP, "ai", note, answer[1])
    return reviewed


def run(ctx: StepContext, files: list[UploadedFile]) -> ManuscriptStructure:
    try:
        outcome = dispatcher.parse_uploads(ctx.workspace.uploads, files)
    except Exception as exc:  # parser failures should be readable, not a traceback
        if {f.extension for f in files if f.kind == "manuscript"} != {".docx"}:
            raise StepError(f"Could not read the manuscript: {exc}") from exc
        ctx.log(STEP, f"The Word reader stopped with {exc.__class__.__name__}: {exc}", "warning")
        raise StepError(f"Could not read the manuscript: {WORD_FILE_UNREADABLE}") from exc
    m = outcome.manuscript
    ctx.log(STEP, f"Parsed {outcome.primary.name} ({m.source.format}) deterministically: "
                  f"{len(m.all_sections())} sections, {len(m.figures)} figures, {len(m.tables)} tables, "
                  f"{len(m.references)} references, confidence {m.source.confidence:.2f}")
    for note in outcome.bib_changes[:20]:
        ctx.log(STEP, f"BibTeX cleanup: {note}")
    for note in outcome.bib_warnings[:20]:
        ctx.log(STEP, note, "warning")
    m.source.warnings.extend(outcome.bib_warnings)

    ambiguous = m.source.confidence < CONFIDENCE_THRESHOLD and m.source.format == "docx"
    ai = ctx.ai
    if ai is not None and ai.full:
        text = dispatcher.plain_text_of(outcome.primary, 30000)
        if ambiguous:
            ctx.log(STEP, "The parser could not read this Word file well; asking the content agent for an outline.")
            result = _outline_step(ctx, m, text) if ai.can_ask else None
        else:
            ctx.log(STEP, "Content agent is reviewing the parser's draft against your text.")
            result = _review_step(ctx, m, text) if ai.can_ask else None
        if result is None:
            ctx.log(STEP, f"Using the parser's structure: {ai.fallback(STEP)}.", "warning")
        else:
            m = result
    elif ambiguous and ai is not None and ai.enabled:
        ctx.log(STEP, "Structure is ambiguous; asking the configured AI for an outline (1 call).")
        text = dispatcher.plain_text_of(outcome.primary, 30000)
        result = _outline_step(ctx, m, text)
        if result is None:
            ctx.log(STEP, f"Using the parser's structure: {ai.fallback(STEP)}.", "warning")
        else:
            m = result
    else:
        if ambiguous:
            ctx.log(STEP, "Structure is ambiguous and AI is off, so the parser's result is used. "
                          "Check headings in the output.", "warning")
        if ai is not None:
            ai.record(STEP, "rules", f"Parsed by the {m.source.format} parser.")

    out = ctx.workspace.work.parent / "manuscript.json"
    out.write_text(m.model_dump_json(indent=2), encoding="utf-8")
    ctx.data["primary_file"] = outcome.primary.name
    ctx.log(STEP, f"Title: {plain_title(m)[:100] or '(not found)'}", "success")
    return m
