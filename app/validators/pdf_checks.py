"""Checks that inspect the generated PDF."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from app.models.report import CheckResult
from app.models.venue import VenueCheck
from app.validators.registry import CheckContext, register, result


def _no_pdf(check: VenueCheck) -> CheckResult:
    return result(check, False, f"{check.description}: not checked because no PDF was produced.")


def main_text_pages(doc, headings: list[str]) -> int:
    """Pages of main text: up to the first of ``headings`` (such as References), counting the page it starts
    on only when main text comes before it there. Running headers, footers and line numbers are ignored."""
    pattern = re.compile(r"((\d+|[A-Z])(\.\d+)*\.?\s+)?(" + "|".join(map(re.escape, headings)) + ")", re.I)
    pages = [[line.strip() for block in page.get_text("blocks") for line in block[4].splitlines() if line.strip()]
             for page in doc]
    seen = Counter(line for lines in pages for line in set(lines))
    repeated = {line for line, n in seen.items() if n > 1 and n > len(pages) / 2}
    for number, lines in enumerate(pages):
        before = 0
        for line in lines:
            if pattern.fullmatch(line):
                return number + (before > 10)
            if line not in repeated and not re.fullmatch(r"[\d\s]+", line):
                before += len(line)
    return len(pages)


@register("page_limit")
def page_limit(ctx: CheckContext, check: VenueCheck) -> CheckResult:
    pdf = ctx.pdf_path
    if not pdf:
        return _no_pdf(check)
    import pymupdf as fitz

    ends = check.params.get("main_ends_before")
    with fitz.open(str(pdf)) as doc:
        pages = doc.page_count
        main = main_text_pages(doc, ends) if ends else None
    limits = ctx.spec.layout.page_limit
    if main is not None:  # venues that limit only the main text
        evidence = {"pages": pages, "main_pages": main, "max_main": limits.max_pages_main,
                    "max_total": limits.max_pages_total}
        if limits.max_pages_main and main > limits.max_pages_main:
            return result(check, False, f"The main text runs to {main} pages; the limit is {limits.max_pages_main}.",
                          evidence=evidence)
        if limits.max_pages_total and pages > limits.max_pages_total:
            return result(check, False, f"{pages} pages in all; the limit is {limits.max_pages_total}.",
                          evidence=evidence)
        return result(check, True, f"Main text fills {main} page(s); {limits.max_pages_main} allowed "
                                   f"({pages} page(s) in all).", evidence=evidence)
    warn_above = check.params.get("warn_above", limits.max_pages_main)
    fail_above = check.params.get("fail_above", limits.max_pages_total or limits.max_pages_main)
    evidence = {"pages": pages, "warn_above": warn_above, "fail_above": fail_above}
    if fail_above is not None and pages > fail_above:
        return result(check, False, f"{pages} pages exceeds the maximum of {fail_above}.", evidence=evidence)
    if warn_above is not None and pages > warn_above:
        return CheckResult(check_id=check.id, type=check.type, status="warning",
                           message=f"{pages} pages: over the {warn_above}-page limit; extra pages usually need overlength fees.",
                           evidence=evidence)
    return result(check, True, f"{pages} page(s), within the limit.", evidence=evidence)


@register("paper_size")
def paper_size(ctx: CheckContext, check: VenueCheck) -> CheckResult:
    pdf = ctx.pdf_path
    if not pdf:
        return _no_pdf(check)
    import pymupdf as fitz

    defaults = {"letter": (612, 792), "a4": (595.3, 841.9)}[ctx.spec.layout.paper_size]
    w_target = check.params.get("width_pt", defaults[0])
    h_target = check.params.get("height_pt", defaults[1])
    tol = check.params.get("tolerance_pt", 2)
    bad = []
    with fitz.open(str(pdf)) as doc:
        for page in doc:
            r = page.rect
            if abs(r.width - w_target) > tol or abs(r.height - h_target) > tol:
                bad.append(f"page {page.number + 1}: {r.width:.0f} x {r.height:.0f} pt")
    if bad:
        return result(check, False, f"Page size is not {ctx.spec.layout.paper_size}.", details=bad[:10])
    return result(check, True, f"All pages are {ctx.spec.layout.paper_size} ({w_target:g} x {h_target:g} pt).")


@register("fonts_embedded")
def fonts_embedded(ctx: CheckContext, check: VenueCheck) -> CheckResult:
    pdf = ctx.pdf_path
    if not pdf:
        return _no_pdf(check)
    import pymupdf as fitz

    missing: set[str] = set()
    total: set[str] = set()
    with fitz.open(str(pdf)) as doc:
        for page in doc:
            for font in page.get_fonts(full=True):
                # (xref, ext, type, basefont, name, encoding, referencer)
                ext, ftype, basefont = font[1], font[2], font[3]
                total.add(basefont)
                if ext in ("n/a", "") and ftype != "Type3":
                    missing.add(basefont)
    if missing:
        details = sorted(missing)[:20]
        if figures := _figures_using(missing, ctx):
            details.append(f"They come from figure file(s) {', '.join(figures)}: export them again with fonts "
                           "embedded (for example 'Save as PDF' with font embedding on).")
        return result(check, False, f"{len(missing)} font(s) are not embedded.", details=details)
    return result(check, True, f"All {len(total)} fonts are embedded.")


def _figures_using(fonts: set[str], ctx: CheckContext) -> list[str]:
    """The PDF figures that bring in any of these fonts without embedding them."""
    import pymupdf as fitz

    root = Path(ctx.project.root_dir)
    found = []
    for name in ctx.project.figure_files:
        if not name.lower().endswith(".pdf") or not (root / name).is_file():
            continue
        with fitz.open(str(root / name)) as doc:
            if any(font[3] in fonts and font[1] in ("n/a", "") for page in doc for font in page.get_fonts(full=True)):
                found.append(Path(name).name)
    return found
