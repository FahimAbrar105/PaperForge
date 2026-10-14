"""Bookkeeping shared by the parsers that read a document from top to bottom (Markdown and Word)."""

from __future__ import annotations

import re

from app.models.manuscript import Author, Reference, Section, TextBlock

REFERENCE_TITLES = {"references", "bibliography", "works cited", "literature cited"}
ACK_TITLES = {"acknowledgment", "acknowledgments", "acknowledgement", "acknowledgements"}
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
SUPERSCRIPTS = "\u2070\u00b9\u00b2\u00b3\u2074\u2075\u2076\u2077\u2078\u2079"
SUPERSCRIPT_DIGITS = str.maketrans(SUPERSCRIPTS, "0123456789")
TO_SUPERSCRIPT = str.maketrans("0123456789", SUPERSCRIPTS)


def special_part(title: str) -> str | None:
    """'abstract', 'references' or 'ack' when a heading starts that part of a paper, else None."""
    low = title.lower().strip(" :.")
    if low == "abstract":
        return "abstract"
    if low in REFERENCE_TITLES:
        return "references"
    if low in ACK_TITLES:
        return "ack"
    return None


class Outline:
    """Collects sections, abstract, acknowledgments and a plain reference list while a parser reads a paper.

    ``part`` says where the text being read belongs: "body", "abstract", "references" or "ack".
    The Word parser also starts in "front" for the title and author lines.
    """

    def __init__(self, part: str = "body") -> None:
        self.part = part
        self.sections: list[Section] = []
        self.preface: list[TextBlock] = []  # body text before the first heading
        self.abstract: list[str] = []
        self.acknowledgments: list[str] = []
        self.references: list[Reference] = []
        self._open: list[Section] = []  # the current section and its parents

    @property
    def blocks(self) -> list[TextBlock]:
        """Where body blocks go right now: the current section, or the text before the first heading."""
        return self._open[-1].blocks if self._open else self.preface

    def heading(self, title: str, level: int, label: str | None = None) -> None:
        """Start a section, or switch part for an Abstract, References or Acknowledgments heading."""
        part = special_part(title)
        if part:
            self.part = part
            return
        self.part = "body"
        section = Section(title=title, level=max(1, min(level, 4)), label=label)
        while self._open and self._open[-1].level >= section.level:
            self._open.pop()
        (self._open[-1].subsections if self._open else self.sections).append(section)
        self._open.append(section)

    def add(self, block: TextBlock) -> None:
        """Add a block to the current part. Figures and tables always stay in the body."""
        if self.part not in {"abstract", "ack", "references"} or block.kind in {"figure_ref", "table_ref"}:
            self.blocks.append(block)
        elif self.part == "abstract":
            self.abstract.append(block.content)
        elif self.part == "ack":
            self.acknowledgments.append(block.content)
        else:
            for item in block.items or [block.content]:
                self.add_reference(item)

    def add_reference(self, text: str) -> None:
        entry = re.sub(r"^\s*(\[\d+\]|\d+[.)])\s*", "", text).strip()
        if entry:
            self.references.append(Reference(key=f"ref{len(self.references) + 1}", entry_type="misc",
                                             fields={"raw": entry}, origin="reference_list_text"))

    def all_sections(self) -> list[Section]:
        """The section tree; text before the first heading becomes an untitled first section."""
        if self.preface:
            return [Section(title="*", level=1, blocks=self.preface), *self.sections]
        return self.sections


def nested_list_latex(entries: list[tuple[int, bool, str]]) -> str:
    """LaTeX for a list with sub-items. ``entries`` are (indent or level, ordered, item LaTeX) in reading order."""
    lines: list[str] = []
    open_lists: list[tuple[int, str]] = []  # (indent, environment) of each list still open
    for indent, ordered, item in entries:
        while open_lists and indent < open_lists[-1][0]:
            lines.append(f"\\end{{{open_lists.pop()[1]}}}")
        if not open_lists or indent > open_lists[-1][0]:
            env = "enumerate" if ordered else "itemize"
            open_lists.append((indent, env))
            lines.append(f"\\begin{{{env}}}")
        lines.append("\\item " + item)
    while open_lists:
        lines.append(f"\\end{{{open_lists.pop()[1]}}}")
    return "\n".join(lines)


def authors_from_lines(lines: list[str]) -> list[Author]:
    """Authors from the lines between the title and the abstract.

    Either every line is "Name, Affiliation, email" (one author per line), or the first line lists the
    names and the following lines hold affiliations and emails.
    """
    if not lines:
        return []
    if all(EMAIL_RE.search(line) and "," in line for line in lines):
        authors = []
        for line in lines:
            email = EMAIL_RE.search(line).group(0)
            parts = [x.strip() for x in line.replace(email, "").split(",") if x.strip()]
            if parts and len(parts[0].split()) <= 5:
                affiliation = ", ".join(parts[1:])
                authors.append(Author(name=parts[0], affiliations=[affiliation] if affiliation else [], email=email))
        if authors:
            return authors

    names_line, rest = lines[0].translate(SUPERSCRIPT_DIGITS), lines[1:]
    if marked := authors_by_marker(names_line, rest):
        return marked
    names = re.split(r",?\s+and\s+|,\s*|;\s*", re.sub(r"[\d*\u2020\u2021]+", "", names_line))
    names = [n.strip() for n in names if n.strip() and len(n.split()) <= 5 and not EMAIL_RE.search(n)]
    emails = [m.group(0) for line in rest for m in EMAIL_RE.finditer(line)]
    affiliations = [line for line in rest if not EMAIL_RE.search(line)][:2]
    return [Author(name=name, affiliations=affiliations, email=emails[i] if i < len(emails) else None)
            for i, name in enumerate(names)]


def authors_by_marker(names_line: str, rest: list[str]) -> list[Author] | None:
    """"Ann Lee1, Bo Chen2" over "1MIT, 2Google": give each author the affiliations their markers point to.

    ``names_line`` already has superscript digits turned into plain digits. None when there are no markers.
    """
    parts = [p.strip() for p in re.split(r",?\s+and\s+|,\s*(?!\d)|;\s*", names_line) if p.strip()]
    named = [re.match(r"^(.*?[^\d\s,*])\s*(\d+(?:\s*,\s*\d+)*)?\s*[*\u2020\u2021]*$", p) for p in parts]
    if not named or not all(named) or not any(m.group(2) for m in named):
        return None
    affiliations: dict[str, str] = {}  # marker -> affiliation
    emails: list[str] = []
    for line in rest:
        emails += EMAIL_RE.findall(line)
        text = EMAIL_RE.sub("", line).strip(" ,;")
        if re.search(f"[{SUPERSCRIPTS}]", text):  # "¹Univ. of Lagos ²TU Berlin": each superscript starts one
            pieces = re.split(f"(?<![{SUPERSCRIPTS}])(?=[{SUPERSCRIPTS}])", text)
        else:  # "1 MIT, 2 Google"
            pieces = re.split(r"(?:^|[,;]\s*|\s{2,})(?=\d+\s*[^\d\s,.])", text)
        for piece in pieces:
            if m := re.match(r"^(\d+)\s*(.+)$", piece.translate(SUPERSCRIPT_DIGITS).strip()):
                affiliations[m.group(1)] = m.group(2).strip(" ,;")
    if not affiliations:
        return None
    authors = []
    for i, m in enumerate(named):
        markers = re.findall(r"\d+", m.group(2) or "")
        authors.append(Author(name=m.group(1).strip(), affiliations=[affiliations[k] for k in markers if k in affiliations],
                              email=emails[i] if i < len(emails) else None))
    return authors
