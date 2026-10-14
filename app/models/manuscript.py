from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TextBlock(BaseModel):
    kind: Literal["paragraph", "equation", "list", "code", "figure_ref", "table_ref", "raw_latex"]
    content: str = ""
    format: Literal["latex", "plain", "markdown"] = "plain"
    items: list[str] = Field(default_factory=list)
    ordered: bool = False
    label: str | None = None


class Section(BaseModel):
    title: str
    level: int = Field(default=1, ge=1, le=4)
    label: str | None = None
    blocks: list[TextBlock] = Field(default_factory=list)
    subsections: list["Section"] = Field(default_factory=list)


class SourceInfo(BaseModel):
    primary_file: str
    format: Literal["tex", "md", "docx"]
    parser: Literal["deterministic", "deterministic+gemini", "deterministic+ollama"] = "deterministic"
    confidence: float = Field(default=1.0, ge=0, le=1)
    warnings: list[str] = Field(default_factory=list)


class Author(BaseModel):
    name: str
    affiliations: list[str] = Field(default_factory=list)
    email: str | None = None


class Figure(BaseModel):
    id: str
    file: str
    caption: str = ""
    label: str | None = None
    wide: bool = False
    width_fraction: float | None = None


class Table(BaseModel):
    id: str
    caption: str = ""
    label: str | None = None
    header: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    raw_latex: str | None = None
    wide: bool = False
    # True when the Formatter agent decided the width; otherwise a size heuristic decides.
    wide_decided: bool = False


class Reference(BaseModel):
    key: str
    entry_type: str
    fields: dict[str, str] = Field(default_factory=dict)
    origin: Literal["bibtex", "thebibliography", "reference_list_text"] = "bibtex"


class PreambleExtras(BaseModel):
    packages: list[str] = Field(default_factory=list)
    macros: list[str] = Field(default_factory=list)


class ManuscriptStructure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    source: SourceInfo
    title: str = ""
    authors: list[Author] = Field(default_factory=list)
    abstract: str = ""
    keywords: list[str] = Field(default_factory=list)
    sections: list[Section] = Field(default_factory=list)
    figures: list[Figure] = Field(default_factory=list)
    tables: list[Table] = Field(default_factory=list)
    acknowledgments: str | None = None
    ccs: str | None = None  # ACM's CCS concepts (CCSXML block and \ccsdesc lines), printed only by ACM
    appendices: list[Section] = Field(default_factory=list)
    references: list[Reference] = Field(default_factory=list)
    citation_keys_used: list[str] = Field(default_factory=list)
    preamble_extras: PreambleExtras = Field(default_factory=PreambleExtras)
    # Text format of title/abstract/paragraph content: LaTeX sources keep raw LaTeX.
    text_format: Literal["latex", "plain", "markdown"] = "plain"

    def all_sections(self) -> list[Section]:
        return flatten_sections(self.sections)


def flatten_sections(sections: list[Section]) -> list[Section]:
    """Every section and subsection, in reading order."""
    out: list[Section] = []
    for section in sections:
        out.append(section)
        out.extend(flatten_sections(section.subsections))
    return out


def nest_sections(flat: list[Section]) -> list[Section]:
    """Build the section tree from sections listed in reading order, using their levels."""
    roots: list[Section] = []
    open_sections: list[Section] = []
    for section in flat:
        while open_sections and open_sections[-1].level >= section.level:
            open_sections.pop()
        (open_sections[-1].subsections if open_sections else roots).append(section)
        open_sections.append(section)
    return roots
