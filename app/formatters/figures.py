"""Figure file resolution, conversion and LaTeX rendering."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable

from app.models.manuscript import Figure
from app.parsers.text_utils import latex_escape
from app.services.workspace import sanitize_filename

SEARCH_EXT = [".pdf", ".png", ".jpg", ".jpeg", ".eps", ".svg"]
DIRECT_EXT = {".pdf", ".png", ".jpg", ".jpeg"}


def resolve_figure(ref: str, upload_dir: Path) -> Path | None:
    """Find an uploaded file for a figure reference like 'figures/arch' or 'arch.png'."""
    base = Path(ref.replace("\\", "/").strip()).name
    if not base:
        return None
    files = {p.name.lower(): p for p in upload_dir.iterdir() if p.is_file()}
    names = [base, sanitize_filename(base)]
    for name in names:
        hit = files.get(name.lower())
        if hit and hit.suffix.lower() in SEARCH_EXT:
            return hit
    # No exact match: try every image extension, e.g. 'arch' or 'arch.eps' -> 'arch.pdf'.
    clean = sanitize_filename(base)
    stem = Path(clean).stem if Path(base).suffix.lower() in SEARCH_EXT else clean
    for ext in SEARCH_EXT:
        if hit := files.get(f"{stem.lower()}{ext}"):
            return hit
    return None


def prepare_figure(src: Path, figures_dir: Path) -> tuple[str | None, str | None]:
    """Copy/convert a figure into figures/. Returns (latex_filename, problem)."""
    figures_dir.mkdir(parents=True, exist_ok=True)
    ext = src.suffix.lower()
    if ext in DIRECT_EXT:
        target = figures_dir / src.name
        if not target.exists():
            shutil.copyfile(src, target)
        return target.name, None
    if ext == ".svg":
        try:
            import pymupdf as fitz

            with fitz.open(str(src)) as svg:
                pdf_bytes = svg.convert_to_pdf()
            target = figures_dir / f"{src.stem}.pdf"
            target.write_bytes(pdf_bytes)
            return target.name, None
        except Exception as exc:  # PyMuPDF raises various errors for invalid SVG
            return None, f"{src.name}: SVG could not be converted to PDF ({exc.__class__.__name__})."
    if ext == ".eps":
        return None, f"{src.name}: EPS figures must be converted to PDF or PNG before upload."
    return None, f"{src.name}: unsupported figure format."


def placeholder(name: str, width: str = "\\columnwidth") -> str:
    return (
        f"\\fbox{{\\parbox[c][0.35{width}][c]{{0.9{width}}}{{\\centering\\small "
        f"Missing figure: \\texttt{{{latex_escape(name)}}}}}}}"
    )


def render_figure(fig: Figure, latex_name: str | None, convert: Callable[[str], str]) -> str:
    env = "figure*" if fig.wide else "figure"
    width_ref = "\\textwidth" if fig.wide else "\\columnwidth"
    frac = fig.width_fraction if fig.width_fraction and 0.1 <= fig.width_fraction <= 1 else 1.0
    width = f"{frac:g}{width_ref}" if frac != 1.0 else width_ref
    lines = [f"\\begin{{{env}}}[t]", "\\centering"]
    if latex_name:
        lines.append(f"\\includegraphics[width={width},height=0.45\\textheight,keepaspectratio]{{{latex_name}}}")
    else:
        lines.append(placeholder(Path(fig.file).name or fig.id, width_ref))
    if fig.caption:
        lines.append(f"\\caption{{{convert(fig.caption)}}}")
    if fig.label:
        lines.append(f"\\label{{{fig.label}}}")
    lines.append(f"\\end{{{env}}}")
    return "\n".join(lines)
