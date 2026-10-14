"""BibTeX loading and cleaning (bibtexparser 1.x).

Cleaning is conservative: it fixes formatting problems that break BibTeX or the
IEEE style, and never invents bibliographic data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import bibtexparser
from bibtexparser.bparser import BibTexParser

from app.models.manuscript import Reference

STANDARD_TYPES = {
    "article", "book", "booklet", "conference", "inbook", "incollection", "inproceedings", "manual",
    "mastersthesis", "misc", "phdthesis", "proceedings", "techreport", "unpublished", "electronic",
    "patent", "periodical", "standard",
}
TYPE_ALIASES = {
    "online": "misc",
    "www": "misc",
    "webpage": "misc",
    "software": "misc",
    "dataset": "misc",
    "report": "techreport",
    "thesis": "phdthesis",
    "collection": "book",
    "reference": "book",
}
REQUIRED_FIELDS = {
    "article": ["author", "title", "journal", "year"],
    "inproceedings": ["author", "title", "booktitle", "year"],
    "conference": ["author", "title", "booktitle", "year"],
    "book": ["title", "publisher", "year"],
    "phdthesis": ["author", "title", "school", "year"],
    "mastersthesis": ["author", "title", "school", "year"],
    "techreport": ["author", "title", "institution", "year"],
    "incollection": ["author", "title", "booktitle", "publisher", "year"],
}
# biblatex field names that the classic BibTeX IEEEtran.bst does not understand.
FIELD_ALIASES = {"journaltitle": "journal", "location": "address", "institution_name": "institution"}
KEY_SAFE = re.compile(r"[^A-Za-z0-9_:\-./+]")


@dataclass
class BibCleanResult:
    references: list[Reference] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)


def _balanced(value: str) -> bool:
    depth = 0
    prev = ""
    for ch in value:
        if ch == "{" and prev != "\\":
            depth += 1
        elif ch == "}" and prev != "\\":
            depth -= 1
            if depth < 0:
                return False
        prev = ch
    return depth == 0


def _escape_unescaped(value: str, chars: str = "&%#") -> str:
    for ch in chars:
        value = re.sub(r"(?<!\\)" + re.escape(ch), "\\" + ch, value)
    return value


def clean_field(name: str, value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    value = value.rstrip(",").strip()
    if name in {"url", "doi", "eprint", "file"}:
        if name == "doi":
            value = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", value, flags=re.I)
        return value
    value = _escape_unescaped(value)
    if name == "pages":
        value = re.sub(r"\s*[-–—]+\s*", "--", value)
    if name == "year":
        m = re.search(r"\b(1[5-9]\d\d|20\d\d|21\d\d)\b", value)
        if m:
            value = m.group(1)
    if name == "month":
        value = value.strip("{}")
    if name == "author" or name == "editor":
        value = re.sub(r"\s+and\s+", " and ", value, flags=re.I)
        value = value.replace(" & ", " and ").replace(" \\& ", " and ")
    return value


def parse_bibtex_text(text: str, source_name: str = "references.bib") -> BibCleanResult:
    result = BibCleanResult()
    # Citation keys containing spaces make bibtexparser drop the entry silently: squeeze them first.
    def squeeze(m: re.Match) -> str:
        key = m.group(2)
        fixed = re.sub(r"\s+", "", key)
        if fixed != key.strip():
            result.changes.append(f"Citation key '{key.strip()}' had spaces; renamed to '{fixed}'.")
        return m.group(1) + fixed + ","

    text = re.sub(r"(@(?!string|comment|preamble)\w+\s*\{)([^,{}\n]*),", squeeze, text, flags=re.I)
    raw_keys = re.findall(r"@(?!string|comment|preamble)\w+\s*\{\s*([^,\s]+)\s*,", text, flags=re.I)
    parser = BibTexParser(common_strings=True, ignore_nonstandard_types=False)
    parser.homogenise_fields = False
    try:
        db = bibtexparser.loads(text, parser=parser)
    except Exception as exc:  # bibtexparser raises a variety of exceptions on bad input
        result.warnings.append(f"{source_name}: could not be parsed as BibTeX ({exc.__class__.__name__}).")
        return result
    parsed_keys = {e.get("ID", "").strip() for e in db.entries}
    for key in dict.fromkeys(raw_keys):
        if key not in parsed_keys:
            result.warnings.append(f"{source_name}: entry '{key}' has a syntax error (for example unbalanced braces) "
                                   "and was skipped; fix it manually.")
    seen: set[str] = set()
    for entry in db.entries:
        raw_key = entry.get("ID", "").strip()
        etype_raw = entry.get("ENTRYTYPE", "misc").lower().strip()
        key = KEY_SAFE.sub("", raw_key)
        if not key:
            result.warnings.append(f"{source_name}: skipped an entry without a citation key.")
            continue
        if key != raw_key:
            result.changes.append(f"Citation key '{raw_key}' normalized to '{key}'.")
        if key in seen:
            result.warnings.append(f"Duplicate BibTeX key '{key}' - kept the first entry.")
            continue
        seen.add(key)
        etype = TYPE_ALIASES.get(etype_raw, etype_raw)
        if etype != etype_raw:
            result.changes.append(f"{key}: entry type @{etype_raw} mapped to @{etype} for IEEEtran.bst.")
        if etype not in STANDARD_TYPES:
            result.changes.append(f"{key}: unknown entry type @{etype} mapped to @misc.")
            etype = "misc"
        fields: dict[str, str] = {}
        for name, value in entry.items():
            if name in {"ID", "ENTRYTYPE"}:
                continue
            fname = FIELD_ALIASES.get(name.lower().strip(), name.lower().strip())
            if not isinstance(value, str):
                continue
            cleaned = clean_field(fname, value)
            if not cleaned:
                continue
            if not _balanced(cleaned):
                result.warnings.append(f"{key}: field '{fname}' has unbalanced braces and was dropped.")
                continue
            fields[fname] = cleaned
        if "date" in fields and "year" not in fields:
            m = re.search(r"\b(1[5-9]\d\d|20\d\d|21\d\d)\b", fields["date"])
            if m:
                fields["year"] = m.group(1)
                result.changes.append(f"{key}: year taken from date field.")
        if etype == "misc" and "url" in fields and "howpublished" not in fields:
            fields["howpublished"] = "\\url{" + fields["url"] + "}"
        missing = [f for f in REQUIRED_FIELDS.get(etype, []) if f not in fields]
        if missing:
            result.warnings.append(f"{key}: missing {', '.join(missing)} (needs manual review).")
        result.references.append(Reference(key=key, entry_type=etype, fields=fields, origin="bibtex"))
    return result


def parse_bibtex_file(path: Path) -> BibCleanResult:
    text = path.read_text(encoding="utf-8", errors="replace")
    return parse_bibtex_text(text, path.name)


def _quote_value(name: str, value: str) -> str:
    if name in {"year"} and value.isdigit():
        return value
    if name == "month" and value.lower()[:3] in {"jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"} and len(value) <= 4:
        return value.lower()[:3]
    return "{" + value + "}"


FIELD_ORDER = ["author", "title", "journal", "booktitle", "editor", "volume", "number", "pages", "publisher",
               "school", "institution", "organization", "address", "month", "year", "doi", "url", "howpublished", "note"]


def write_bibtex(references: list[Reference]) -> str:
    """Serialize references back to BibTeX in a stable, readable layout."""
    chunks = []
    for ref in references:
        if ref.origin != "bibtex":
            continue
        names = sorted(ref.fields, key=lambda n: (FIELD_ORDER.index(n) if n in FIELD_ORDER else len(FIELD_ORDER), n))
        lines = [f"@{ref.entry_type}{{{ref.key},"]
        for n in names:
            lines.append(f"  {n} = {_quote_value(n, ref.fields[n])},")
        lines.append("}")
        chunks.append("\n".join(lines))
    return "\n\n".join(chunks) + ("\n" if chunks else "")
