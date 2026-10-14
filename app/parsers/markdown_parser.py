"""Deterministic Markdown manuscript parser.

Supported conventions (Pandoc-compatible where possible):

* Optional YAML front matter with ``title``, ``author``/``authors`` (strings or
  mappings with name/affiliation/email), ``abstract``, ``keywords``,
  ``bibliography``.
* Without front matter: the first ``#`` heading is the title, an ``Abstract``
  heading or a paragraph starting with ``Abstract:`` is the abstract, and a
  ``Keywords:``/``Index Terms:`` line gives keywords.
* Headings, paragraphs, bullet/numbered lists, fenced code, ``$$`` display math,
  images ``![caption](file){#fig:label}``, pipe tables with a ``Table: caption``
  line, citations ``[@key]`` / ``[@a; @b]`` / ``[@a, p. 4]`` / ``\\cite{key}``, footnotes
  ``[^1]`` with ``[^1]: text`` and inline ``^[text]``, nested lists.
* A ``References`` section with plain-text entries when no .bib is supplied.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.models.manuscript import Author, Figure, ManuscriptStructure, SourceInfo, Table, TextBlock
from app.formatters.markdown_to_latex import html_attr, inline_md
from app.parsers.outline import TO_SUPERSCRIPT, Outline, authors_from_lines, nested_list_latex
from app.parsers.text_utils import strip_heading_number

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*(\{#([^}]+)\})?\s*$")
IMAGE_RE = re.compile(r"^!\[(.*?)\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)\s*(\{([^}]*)\})?\s*$")
CITE_MD_RE = re.compile(r"\[([^\[\]@]*(?<![\w.])-?@[\w:.\-/+]+[^\[\]]*)\](?!\()")
CITE_KEY_RE = re.compile(r"(?<![\w.])-?@([\w:.\-/+]+)")
FOOTNOTE_DEF_RE = re.compile(r"^\[\^([^\]\s]+)\]:\s?(.*)$")
CITE_TEX_RE = re.compile(r"\\cite[a-z]*\{([^}]+)\}")
LIST_RE = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
TABLE_CAPTION_RE = re.compile(r"^(?:Table(?:\s+(?:\d+|[IVX]+))?\s*[:.]|:\s)\s*(.*?)\s*(\{#([^}]+)\})?\s*$", re.I)
TABLE_CAPTION_BEFORE_RE = re.compile(r"^Table(?:\s+(?:\d+|[IVX]+))?\s*[:.]\s*(.*?)\s*(\{#([^}]+)\})?$", re.I)
FIGURE_CAPTION_RE = re.compile(r"^Fig(?:ure|\.)?\s*(?:\d+|[IVX]+)\s*[:.]\s*(.*)$", re.I)
NUMBERED_ENTRY_RE = re.compile(r"^(\[\d+\]|\d+[.)])\s")
HTML_IMG_RE = re.compile(r"^(?:<(?:p|div|center|figure)\b[^<>]*>\s*)?<img\b([^<>]*)>(?:\s*</(?:p|div|center)>)?$", re.I)
HTML_ONLY_TAGS_RE = re.compile(r"^(?:</?(?:p|div|center|figure|section|span|br|hr)\b[^<>]*>\s*)+$", re.I)
FIGCAPTION_RE = re.compile(r"^<figcaption>(.*?)</figcaption>(?:\s*</figure>)?$", re.I)


# ----------------------------------------------------------------------------- mini YAML
def _split_inline(text: str) -> list[str]:
    parts, buf, quote = [], [], None
    for ch in text:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch == ",":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return parts


YAML_ESCAPES = {"\\": "\\", '"': '"', "n": "\n", "t": "\t"}


def _scalar(value: str):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        # \n or \t right before a letter is LaTeX (\nu, \theta, \textbf), not a newline or a tab.
        return re.sub(r'\\(\\|"|[nt](?![A-Za-z]))', lambda m: YAML_ESCAPES[m.group(1)], value[1:-1])
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1]
    if value.startswith("[") and value.endswith("]"):
        return [_scalar(v) for v in _split_inline(value[1:-1]) if v.strip()]
    return value


def parse_front_matter(text: str) -> tuple[dict, str]:
    """Parse a small, safe subset of YAML: scalars, lists, lists of mappings, block scalars."""
    if not text.startswith("---"):
        return {}, text
    m = re.match(r"^---\s*\n(.*?)\n(?:---|\.\.\.)\s*(?:\n|$)", text, re.S)
    if not m:
        return {}, text
    lines = m.group(1).splitlines()
    data: dict = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        km = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", line)
        if not km:
            i += 1
            continue
        key, rest = km.group(1).lower(), km.group(2)
        i += 1
        if rest.strip() in {"|", ">", "|-", ">-"}:
            block = []
            while i < len(lines) and (lines[i].startswith(" ") or not lines[i].strip()):
                block.append(lines[i].strip())
                i += 1
            joiner = "\n" if rest.strip().startswith("|") else " "
            data[key] = joiner.join(block).strip()
            continue
        if rest.strip():
            data[key] = _scalar(rest)
            continue
        items: list = []
        indent, list_key = 0, None  # list_key: a key of the mapping item above whose value is an indented list
        while i < len(lines) and (lines[i].startswith((" ", "\t", "-")) or not lines[i].strip()):
            item_line = lines[i]
            i += 1
            if not item_line.strip():
                continue
            im = re.match(r"^(\s*)-\s*(.*)$", item_line)
            if im and list_key and len(im.group(1)) > indent:
                items[-1][list_key] = (items[-1][list_key] or []) + [_scalar(im.group(2))]
            elif im:
                indent, list_key = len(im.group(1)), None
                content = im.group(2)
                kv = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", content)
                if kv:
                    items.append({kv.group(1).lower(): _scalar(kv.group(2))})
                    list_key = None if kv.group(2).strip() else kv.group(1).lower()
                else:
                    items.append(_scalar(content))
            else:
                kv = re.match(r"^\s+([A-Za-z_][\w-]*)\s*:\s*(.*)$", item_line)
                if kv and items and isinstance(items[-1], dict):
                    items[-1][kv.group(1).lower()] = _scalar(kv.group(2))
                    list_key = None if kv.group(2).strip() else kv.group(1).lower()
                elif items and isinstance(items[-1], str):
                    items[-1] += " " + item_line.strip()
        data[key] = items
    return data, text[m.end():]


def _as_list(value) -> list:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    return [v.strip() for v in str(value).split(",") if v.strip()]


def authors_from_meta(value) -> list[Author]:
    if isinstance(value, str):
        value = [a for a in re.split(r"\s*;\s*|\s+and\s+", value) if a.strip()]
    authors = []
    for item in _as_list(value):
        if isinstance(item, dict):
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            affs = item.get("affiliation") or item.get("affiliations") or item.get("institute") or []
            if not isinstance(affs, list):
                affs = [affs]  # one string is one affiliation, commas and all
            authors.append(Author(name=name, affiliations=[str(a) for a in affs],
                                  email=str(item["email"]) if item.get("email") else None))
        elif str(item).strip():
            authors.append(Author(name=str(item).strip()))
    return authors


# ----------------------------------------------------------------------------- body helpers
def _is_table_row(line: str) -> bool:
    s = line.strip()
    return s.startswith("|") and s.endswith("|") and s.count("|") >= 2


def _split_row(line: str) -> list[str]:
    """Cells of a pipe-table row. ``\\|`` and a pipe inside `code` belong to the cell."""
    row = line.strip()
    row = row[1:] if row.startswith("|") else row
    row = row[:-1] if row.endswith("|") and not row.endswith("\\|") else row
    cells, cell, in_code = [], "", False
    i = 0
    while i < len(row):
        ch = row[i]
        if ch == "\\" and row[i + 1 : i + 2] == "|":
            cell += "|"
            i += 2
            continue
        if ch == "`":
            in_code = not in_code
        if ch == "|" and not in_code:
            cells.append(cell.strip())
            cell = ""
        else:
            cell += ch
        i += 1
    return cells + [cell.strip()]


def _is_separator(line: str) -> bool:
    return bool(re.fullmatch(r"\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*", line))


def collect_citations(text: str) -> list[str]:
    keys: list[str] = []
    for m in CITE_MD_RE.finditer(text):
        for k in CITE_KEY_RE.findall(m.group(1)):
            k = k.rstrip(".")
            if k not in keys:
                keys.append(k)
    for m in CITE_TEX_RE.finditer(text):
        for k in m.group(1).split(","):
            if k.strip() and k.strip() not in keys:
                keys.append(k.strip())
    return keys


# ----------------------------------------------------------------------------- parser
class _Reader:
    """Reads the Markdown body line by line into an Outline, figures and tables."""

    def __init__(self, lines: list[str], base_level: int, keywords: list[str], has_abstract: bool) -> None:
        self.lines = lines
        self.i = 0
        self.base_level = base_level  # the largest heading level used, which becomes \section
        self.keywords = keywords
        self.has_abstract = has_abstract
        self.outline = Outline()
        self.figures: list[Figure] = []
        self.tables: list[Table] = []
        self.warnings: list[str] = []
        self.para: list[str] = []

    def read(self) -> None:
        while self.i < len(self.lines):
            line = self.lines[self.i]
            stripped = line.strip()
            if stripped.startswith(("```", "~~~")):
                self.read_code(stripped[:3])
            elif stripped.startswith("$$"):
                self.read_math(stripped)
            elif heading := HEADING_RE.match(line):
                self.read_heading(heading)
            elif image := IMAGE_RE.match(stripped):
                self.read_image(image.group(1), image.group(2), image.group(4) or "")
            elif image := HTML_IMG_RE.match(stripped):
                self.read_image(html_attr(image.group(1), "alt"), html_attr(image.group(1), "src"),
                                f'width={html_attr(image.group(1), "width")}')
            elif stripped.startswith("<!--"):
                self.skip_comment()
            elif caption := FIGCAPTION_RE.match(stripped):
                self.flush_para()
                if self.after_figure():
                    self.figures[-1].caption = caption.group(1).strip()
                self.i += 1
            elif HTML_ONLY_TAGS_RE.match(stripped):
                self.flush_para()
                self.i += 1
            elif stripped.startswith(">") and not self.para:
                self.read_quote()
            elif _is_table_row(line) and self.i + 1 < len(self.lines) and _is_separator(self.lines[self.i + 1]):
                self.read_table(line)
            elif LIST_RE.match(line) and not self.para:
                self.read_list()
            elif not stripped:
                self.flush_para()
                self.i += 1
            else:
                self.para.append(stripped.lstrip("> ") if stripped.startswith(">") else stripped)
                self.i += 1
        self.flush_para()

    def flush_para(self) -> None:
        content = " ".join(p.strip() for p in self.para).strip()
        self.para.clear()
        if not content:
            return
        keywords = re.match(r"^\**\s*(keywords|index terms)\s*\**\s*[:\u2014-]+\s*\**\s*(.*)$", content, re.I)
        abstract = re.match(r"^\**\s*abstract\s*\**\s*[:.\u2014-]+\s*\**\s*(.*)$", content, re.I | re.S)
        figure_caption = FIGURE_CAPTION_RE.match(content)
        outline = self.outline
        if keywords and not self.keywords:
            self.keywords.extend(k.strip().rstrip(".") for k in re.split(r"[,;]", keywords.group(2)) if k.strip())
        elif figure_caption and self.after_figure():
            self.figures[-1].caption = figure_caption.group(1)
        elif (abstract and not self.has_abstract and not outline.abstract and outline.part == "body"
              and not outline.sections):
            outline.abstract.append(abstract.group(1).strip())
        elif outline.part == "references" and NUMBERED_ENTRY_RE.match(content):
            # A run of numbered references without blank lines between them.
            for entry in re.split(r"\s(?=\[\d+\]\s)", content):
                outline.add_reference(entry)
        else:
            outline.add(TextBlock(kind="paragraph", content=content, format="markdown"))

    def after_figure(self) -> bool:
        """Right below an image, where a "Figure 1: ..." paragraph or <figcaption> is its caption (not the alt text)."""
        blocks = self.outline.blocks
        return bool(blocks) and blocks[-1].kind == "figure_ref"

    def read_code(self, fence: str) -> None:
        self.flush_para()
        code = []
        self.i += 1
        while self.i < len(self.lines) and not self.lines[self.i].strip().startswith(fence):
            code.append(self.lines[self.i])
            self.i += 1
        self.i += 1
        self.outline.add(TextBlock(kind="code", content="\n".join(code), format="plain"))

    def read_math(self, stripped: str) -> None:
        self.flush_para()
        rest = stripped[2:]
        self.i += 1
        trailing = ""
        if "$$" in rest:
            inner, _, trailing = rest.partition("$$")
            math = [inner]
        else:
            math = [rest]
            while self.i < len(self.lines) and "$$" not in self.lines[self.i]:
                math.append(self.lines[self.i])
                self.i += 1
            if self.i < len(self.lines):
                before, _, trailing = self.lines[self.i].partition("$$")
                math.append(before)
                self.i += 1
            else:
                self.warnings.append("Unclosed $$ display math block.")
        content = "\n".join(math).strip()
        latex_label = re.search(r"\\label\{([^}]+)\}", content)
        pandoc_label = re.search(r"\{#([^}\s]+)\}", trailing)
        label = latex_label.group(1) if latex_label else pandoc_label.group(1) if pandoc_label else None
        content = re.sub(r"\\label\{[^}]+\}", "", content).strip()
        self.outline.add(TextBlock(kind="equation", content=content, format="latex", label=label))

    def read_heading(self, m: re.Match) -> None:
        self.flush_para()
        level = len(m.group(1)) - self.base_level + 1
        self.outline.heading(strip_heading_number(m.group(2).strip()), level, label=m.group(4))
        self.i += 1

    def skip_comment(self) -> None:
        self.flush_para()
        while self.i < len(self.lines) and "-->" not in self.lines[self.i]:
            self.i += 1
        self.i += 1

    def read_quote(self) -> None:
        """A '> quote' block (with any lazy continuation lines) becomes a quote environment."""
        lines = []
        while self.i < len(self.lines) and self.lines[self.i].strip():
            lines.append(re.sub(r"^\s*>\s?", "", self.lines[self.i]))
            self.i += 1
        text = " ".join(line.strip() for line in lines if line.strip())
        if self.outline.part == "body":
            self.outline.add(TextBlock(kind="raw_latex", content=f"\\begin{{quote}}\n{inline_md(text)}\n\\end{{quote}}",
                                       format="latex"))
        else:
            self.para.append(text)
            self.flush_para()

    def read_image(self, caption: str, file: str, attrs: str) -> None:
        """An image on its own line becomes a figure: ![caption](file){#fig:label width=50% .wide},
        or an HTML <img src=... alt=...> line."""
        self.flush_para()
        self.i += 1
        if not file.strip():
            return
        label = re.search(r"#([\w:.-]+)", attrs)
        width = re.search(r"width\s*=\s*\"?(\d+(?:\.\d+)?)%", attrs)
        fig = Figure(id=f"fig{len(self.figures) + 1}", file=file.strip(), caption=caption.strip(),
                     label=label.group(1) if label else None,
                     wide=bool(re.search(r"(^|\s)\.?wide\b", attrs)),
                     width_fraction=float(width.group(1)) / 100 if width else None)
        self.figures.append(fig)
        self.outline.add(TextBlock(kind="figure_ref", content=fig.id))

    def read_table(self, header_line: str) -> None:
        self.flush_para()
        header = _split_row(header_line)
        self.i += 2  # header and separator
        rows = []
        while self.i < len(self.lines) and _is_table_row(self.lines[self.i]):
            rows.append(_split_row(self.lines[self.i]))
            self.i += 1
        caption, label = self._caption_before_table()
        if not caption:
            caption, label = self._caption_after_table()
        table = Table(id=f"tab{len(self.tables) + 1}", caption=caption, label=label, header=header, rows=rows)
        self.tables.append(table)
        self.outline.add(TextBlock(kind="table_ref", content=table.id))

    def _caption_after_table(self) -> tuple[str, str | None]:
        """A 'Table: caption {#tbl:x}', 'Table 1: caption' or ': caption' line up to two blank lines below the table."""
        j = self.i
        while j < len(self.lines) and not self.lines[j].strip() and j - self.i < 2:
            j += 1
        m = TABLE_CAPTION_RE.match(self.lines[j].strip()) if j < len(self.lines) else None
        if m:
            self.i = j + 1
            return m.group(1), m.group(3)
        return "", None

    def _caption_before_table(self) -> tuple[str, str | None]:
        """A 'Table: caption' or 'Table 1: caption' paragraph right above the table."""
        blocks = self.outline.blocks
        if blocks and blocks[-1].kind == "paragraph":
            m = TABLE_CAPTION_BEFORE_RE.match(blocks[-1].content)
            if m:
                blocks.pop()
                return m.group(1), m.group(3)
        return "", None

    def read_list(self) -> None:
        """A bullet or numbered list. Indented items are sub-items; blank lines between items keep one list."""
        entries: list[tuple[int, bool, str]] = []  # (indent, ordered, text) per item
        while self.i < len(self.lines):
            line = self.lines[self.i]
            if item := LIST_RE.match(line):
                entries.append((len(item.group(1).expandtabs(4)), item.group(2)[0].isdigit(), item.group(3).strip()))
            elif line.strip() and line.startswith((" ", "\t")):
                indent, ordered, text = entries[-1]
                entries[-1] = (indent, ordered, text + " " + line.strip())  # continuation line
            elif not line.strip() and self._list_goes_on():
                continue
            else:
                break
            self.i += 1

        if len({indent for indent, _, _ in entries}) == 1 or self.outline.part != "body":
            items = [text for _, _, text in entries]
            self.outline.add(TextBlock(kind="list", items=items, ordered=entries[0][1], format="markdown"))
        else:
            latex = nested_list_latex([(indent, ordered, inline_md(text)) for indent, ordered, text in entries])
            self.outline.add(TextBlock(kind="raw_latex", content=latex, format="latex"))

    def _list_goes_on(self) -> bool:
        """At a blank line inside a list: skip to the next text line if it is another item or an indented
        continuation (a "loose" list), so the numbering does not restart at 1."""
        j = self.i
        while j < len(self.lines) and not self.lines[j].strip():
            j += 1
        if j < len(self.lines) and (LIST_RE.match(self.lines[j]) or self.lines[j].startswith(("  ", "\t"))):
            self.i = j
            return True
        return False


def _headings(lines: list[str]) -> list[tuple[int, re.Match]]:
    """The '#' headings with their line numbers. A '# comment' in fenced code is not a heading."""
    headings, fence = [], ""
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")) and (not fence or stripped.startswith(fence)):
            fence = "" if fence else stripped[:3]
        elif not fence and (m := HEADING_RE.match(line)):
            headings.append((idx, m))
    return headings


def _take_title(lines: list[str]) -> tuple[str, int]:
    """Use the first '# Heading' as the title and blank out its line. Returns (title, line number)."""
    for idx, m in _headings(lines):
        if len(m.group(1)) == 1:
            lines[idx] = ""
            return m.group(2).strip(), idx
    return "", -1


NAME_PARTICLES = {"van", "von", "de", "der", "den", "da", "di", "del", "la", "le", "du", "dos", "das", "bin", "al"}


def _front_line(line: str) -> str:
    """An author or affiliation line as plain text: <sup>1</sup> and ^1^ markers become superscript digits."""
    line = re.sub(r"<sup>\s*([^<]*?)\s*</sup>|\^([^\^\s]+)\^", lambda m: (m.group(1) or m.group(2)).translate(TO_SUPERSCRIPT),
                  line.strip().rstrip("\\"))
    line = re.sub(r"</?[a-zA-Z][^<>]*>", "", line)
    return re.sub(r"(\*\*|__|(?<!\w)[*_](?=\S))(.+?)\1", r"\2", line).strip()


def _looks_like_names(line: str) -> bool:
    """'Priya Natarajan, Daniel Osei' or 'Ann Lee¹ and Bo Chen²': only short runs of capitalised words."""
    text = re.sub(r"[\d\u00b2\u00b3\u00b9\u2070-\u2079*\u2020\u2021]+", "", line)
    parts = [p.split() for p in re.split(r",|;|&|\band\b", text) if p.strip()]
    return bool(parts) and len(line) < 200 and all(
        len(words) <= 5 and words[0][0].isupper() and all(w[0].isupper() or w in NAME_PARTICLES for w in words)
        for words in parts)


def _take_authors(lines: list[str], start: int) -> list:
    """Without front matter: the author line right below the '# Title', with any affiliation and e-mail lines
    up to the abstract or the first heading. The lines used are blanked out."""
    j = start
    while j < len(lines) and not lines[j].strip():
        j += 1
    if j >= len(lines) or not _looks_like_names(_front_line(lines[j])):
        return []
    taken = []
    for k in range(j, len(lines)):
        line = lines[k].strip()
        if (HEADING_RE.match(line) or re.match(r"^\W*(abstract|keywords|index terms)\b", line, re.I)
                or line.startswith(("|", "!", "```", "$$")) or re.fullmatch(r"[\W_]+", line)
                or len(line) > 160 or (line.endswith(".") and len(line.split()) > 8)):
            break
        if line:
            taken.append(k)
    authors = authors_from_lines([_front_line(lines[k]) for k in taken])
    for k in taken:
        lines[k] = ""
    return authors


def _title_block(lines: list[str]) -> tuple[str, list]:
    """Pandoc's header lines '% Title', '% Ann Lee; Bo Chen', '% Date'. They are removed from ``lines``."""
    header = []
    while lines and lines[0].startswith("% "):
        header.append(lines.pop(0)[2:].strip())
    names = re.split(r"\s*;\s*", header[1]) if len(header) > 1 else []
    return (header[0] if header else ""), [Author(name=n) for n in names if n]


def _inline_footnotes(lines: list[str]) -> list[str]:
    """Move each ``[^id]: text`` definition (with its indented continuation lines) to its ``[^id]``
    reference, as a Pandoc inline note ``^[text]``."""
    kept: list[str] = []
    notes: dict[str, str] = {}
    in_code = False
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if line.strip().startswith(("```", "~~~")):
            in_code = not in_code
        definition = None if in_code else FOOTNOTE_DEF_RE.match(line)
        if not definition:
            kept.append(line)
            continue
        parts = [definition.group(2).strip()]
        while i < len(lines) and lines[i].startswith(("    ", "\t")):
            parts.append(lines[i].strip())
            i += 1
        notes[definition.group(1)] = " ".join(p for p in parts if p)
    if not notes:
        return kept

    def note(m: re.Match) -> str:
        return f"^[{notes[m.group(1)]}]" if m.group(1) in notes else m.group(0)

    return [re.sub(r"\[\^([^\]\s]+)\](?!:)", note, line) for line in kept]


def parse_markdown_text(text: str, filename: str = "paper.md") -> ManuscriptStructure:
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    meta, body = parse_front_matter(text)
    lines = _inline_footnotes(body.split("\n"))
    block_title, block_authors = _title_block(lines)

    authors = authors_from_meta(meta.get("author") or meta.get("authors")) or block_authors
    title = str(meta.get("title", "")).strip() or block_title
    if not title:
        title, title_line = _take_title(lines)
        if title and not authors:
            authors = _take_authors(lines, title_line + 1)
    abstract = str(meta.get("abstract", "")).strip()
    keywords = [str(k) for k in _as_list(meta.get("keywords") or meta.get("index_terms"))]
    levels = [len(m.group(1)) for _, m in _headings(lines)]

    reader = _Reader(lines, base_level=min(levels, default=2), keywords=keywords, has_abstract=bool(abstract))
    reader.read()
    outline = reader.outline
    abstract = abstract or "\n\n".join(outline.abstract)
    sections = outline.all_sections()

    warnings = reader.warnings
    if not title:
        warnings.append("No title found (add a '# Title' line or 'title:' front matter).")
    if not abstract:
        warnings.append("No abstract found (add an '## Abstract' section or 'abstract:' front matter).")
    confidence = 0.4 + (0.2 if title else 0) + (0.15 if abstract else 0) + (0.25 if sections else 0)

    return ManuscriptStructure(
        source=SourceInfo(primary_file=filename, format="md", confidence=min(confidence, 1.0), warnings=warnings),
        title=title,
        authors=authors,
        abstract=abstract,
        keywords=keywords,
        sections=sections,
        figures=reader.figures,
        tables=reader.tables,
        acknowledgments="\n\n".join(outline.acknowledgments) or None,
        references=outline.references,
        citation_keys_used=collect_citations(text),
        text_format="markdown",
    )


def parse_markdown(path: Path) -> ManuscriptStructure:
    return parse_markdown_text(path.read_text(encoding="utf-8", errors="replace"), path.name)


def bibliography_from_front_matter(path: Path) -> list[str]:
    meta, _ = parse_front_matter(path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n"))
    return [Path(str(b)).name for b in _as_list(meta.get("bibliography"))]
