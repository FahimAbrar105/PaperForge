from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

CheckType = Literal[
    "compile_success",
    "page_limit",
    "paper_size",
    "fonts_embedded",
    "document_class",
    "forbidden_packages",
    "required_sections",
    "abstract_length",
    "keywords_present",
    "figures_resolved",
    "citations_resolved",
    "references_resolved",
    "overfull_boxes",
    "missing_glyphs",
    "bibliography_present",
    "anonymity",
    "manual",
    "lone_subsection",
    "citation_as_noun",
    "reference_details",
    "undefined_abbreviations",
    "stray_underscores",
    "abstract_min_length",
    "affiliation_location",
    "spelling_consistency",
    "identifying_text",
    "figure_descriptions",
    "ccs_concepts",
    "no_appendices",
    "abstract_form",
    "figure_resolution",
    "title_style",
    "heading_case",
    "typed_references",
    "numbered_equations",
    "text_pattern",
]


class TemplateFile(BaseModel):
    path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    copy_to_output: bool = True


class TemplateSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    directory: str
    document_class: str
    class_options: list[str] = Field(default_factory=list)
    main_template: str
    section_template: str | None = None
    split_sections: bool = False
    bibliography_style: str | None = None
    # cite: plain \cite only (IEEEtran). natbib_numbers / natbib_author_year: natbib's \citep and \citet work.
    citations: Literal["cite", "natbib_numbers", "natbib_author_year"] = "cite"
    # Packages the class or style file loads itself. The paper's own \usepackage line for one is dropped,
    # because loading it again with other options stops the compile.
    loads_packages: list[str] = Field(default_factory=list)
    # Lines that restore the venue's caption look when the paper loads the caption or subcaption package.
    caption_setup: list[str] = Field(default_factory=list)
    files: list[TemplateFile] = Field(default_factory=list)
    # The class ends run-in headings (\subsubsection, \paragraph) with its own ":" or ".", so the author's
    # trailing period is dropped.
    class_punctuates_run_in_headings: bool = False


class PageLimit(BaseModel):
    max_pages_main: int | None = None
    max_pages_total: int | None = None
    # Extra pages the camera-ready version may use.
    camera_ready_extra_pages: int = 0


class Layout(BaseModel):
    paper_size: Literal["letter", "a4"] = "letter"
    columns: Literal[1, 2] = 2
    page_limit: PageLimit = Field(default_factory=PageLimit)


class KeywordRule(BaseModel):
    max_count: int | None = None
    latex_env: str | None = None
    printed: bool = True  # False when the venue's format has no keywords


class ContentRules(BaseModel):
    abstract_max_words: int | None = None
    keywords: KeywordRule = Field(default_factory=KeywordRule)
    required_sections: list[str] = Field(default_factory=list)
    forbidden_packages: list[str] = Field(default_factory=list)
    anonymous_submission: bool = False
    # How the text names equations, figures, tables, sections and citations: [inside a sentence, at its start].
    # IEEE writes "(2)", "Equation (2)", "Fig. 1" and "Reference [3] shows"; most venues "Eq. (2)" and "Figure 1".
    # A kind left out is not changed.
    reference_words: dict[Literal["equation", "figure", "table", "section", "citation"], tuple[str, str]] = Field(
        default_factory=lambda: {"equation": ("Eq.", "Equation"), "figure": ("Figure", "Figure"),
                                 "table": ("Table", "Table"), "section": ("Section", "Section")})
    table_caption: Literal["above", "below"] = "above"
    sort_keywords: bool = False  # IEEE asks for its Index Terms in alphabetical order
    leading_zero: bool = False  # IEEE writes "0.25", not ".25"
    roman_numbers: bool = False  # IEEE numbers tables and sections I, II, III


class VenueCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: CheckType
    severity: Literal["error", "warning", "manual", "style"]  # style: a writing suggestion; it never fails the paper
    description: str
    params: dict[str, Any] = Field(default_factory=dict)


class VenueSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    venue_id: str = Field(pattern=r"^[a-z0-9_]+$")
    display_name: str
    venue_type: Literal["conference", "journal", "workshop"] = "conference"
    template: TemplateSpec
    layout: Layout
    content_rules: ContentRules
    checks: list[VenueCheck]
    manual_review_items: list[str] = Field(default_factory=list)
    source_rules_file: str | None = None
    generated_at: str | None = None
