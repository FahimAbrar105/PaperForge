from __future__ import annotations

from pydantic import BaseModel, Field


class LaTeXProject(BaseModel):
    """A generated LaTeX project on disk, inside a job's work directory."""

    root_dir: str
    main_file: str = "main.tex"
    section_files: list[str] = Field(default_factory=list)
    bib_file: str | None = "references.bib"
    figure_files: list[str] = Field(default_factory=list)
    template_files: list[str] = Field(default_factory=list)
    missing_figures: list[str] = Field(default_factory=list)
    unconverted_figures: list[str] = Field(default_factory=list)
    changes: list[str] = Field(default_factory=list)  # corrections made to the author's text, and where
