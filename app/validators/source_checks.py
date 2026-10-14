"""Checks that inspect the generated LaTeX source."""

from __future__ import annotations

import re

from app.models.report import CheckResult
from app.models.venue import VenueCheck
from app.parsers.latex_parser import find_command, find_environment, latex_to_plain, parse_packages
from app.parsers.text_utils import word_count
from app.validators.registry import CheckContext, register, result

SECTION_SYNONYMS = {
    "introduction": ["introduction", "intro", "motivation", "background and motivation"],
    "conclusion": ["conclusion", "conclusions", "concluding remarks", "conclusion and future work",
                   "conclusions and future work", "summary", "discussion and conclusion"],
    "related work": ["related work", "related works", "background", "literature review", "prior work"],
}


@register("document_class")
def document_class(ctx: CheckContext, check: VenueCheck) -> CheckResult:
    m = re.search(r"\\documentclass\s*(?:\[([^\]]*)\])?\s*\{([^}]+)\}", ctx.main_tex)
    if not m:
        return result(check, False, "No \\documentclass found in main.tex.")
    opts = [o.strip() for o in (m.group(1) or "").split(",") if o.strip()]
    cls = m.group(2).strip()
    want = check.params.get("class", ctx.spec.template.document_class)
    required = check.params.get("required_options", [])
    missing = [o for o in required if o not in opts]
    if cls != want or missing:
        return result(check, False, f"Uses {cls}[{','.join(opts)}]; expected {want} with {required}.")
    style = check.params.get("package")
    if style and style not in {name for name, _ in parse_packages(ctx.main_tex)}:
        return result(check, False, f"Uses {cls} but not the venue's {style} package.")
    return result(check, True, f"Uses {cls} with options [{', '.join(opts)}]" + (f" and {style}.sty." if style else "."))


@register("forbidden_packages")
def forbidden_packages(ctx: CheckContext, check: VenueCheck) -> CheckResult:
    doc = find_environment(ctx.main_tex, "document")
    preamble = ctx.main_tex[: doc[0]] if doc else ctx.main_tex
    used = {name for name, _ in parse_packages(preamble)}
    forbidden = set(check.params.get("packages", ctx.spec.content_rules.forbidden_packages))
    bad = sorted(used & forbidden)
    if bad:
        return result(check, False, f"Forbidden package(s) loaded: {', '.join(bad)}.")
    return result(check, True, f"No forbidden packages ({len(used)} packages loaded).")


@register("required_sections")
def required_sections(ctx: CheckContext, check: VenueCheck) -> CheckResult:
    titles = [latex_to_plain(t).strip().lower()
              for t in re.findall(r"\\(?:sub)*section\*?\{((?:[^{}]|\{[^{}]*\})*)\}", ctx.main_tex)]
    required = check.params.get("sections", ctx.spec.content_rules.required_sections)
    missing = []
    for req in required:
        options = SECTION_SYNONYMS.get(req.lower(), [req.lower()])
        if not any(any(t == o or t.startswith(o) for o in options) for t in titles):
            missing.append(req)
    if missing:
        return result(check, False, f"Missing section(s): {', '.join(missing)}.", details=[f"Found: {', '.join(titles) or 'none'}"])
    return result(check, True, f"Required sections present: {', '.join(required)}.")


@register("abstract_length")
def abstract_length(ctx: CheckContext, check: VenueCheck) -> CheckResult:
    env = find_environment(ctx.main_tex, "abstract")
    if not env or not env[2].strip() or "Abstract not found" in env[2]:
        return result(check, False, "No abstract found.")
    words = word_count(env[2])
    limit = check.params.get("max_words", ctx.spec.content_rules.abstract_max_words)
    if limit and words > limit:
        return result(check, False, f"Abstract has about {words} words; the limit is {limit}.", evidence={"words": words})
    return result(check, True, f"Abstract has about {words} words" + (f" (limit {limit})." if limit else "."), evidence={"words": words})


@register("keywords_present")
def keywords_present(ctx: CheckContext, check: VenueCheck) -> CheckResult:
    rule = ctx.spec.content_rules.keywords
    env_name = check.params.get("env", rule.latex_env or "keywords")
    found = find_environment(ctx.main_tex, env_name) or find_command(ctx.main_tex, env_name)  # IEEE env, ACM command
    if not found or not found[2].strip():
        return result(check, False, "No keywords / Index Terms found.")
    count = len([k for k in re.split(r"[,;]", found[2]) if k.strip()])
    if rule.max_count and count > rule.max_count:
        return result(check, False, f"{count} keywords; at most {rule.max_count} allowed.")
    return result(check, True, f"{count} keyword(s) present.")


@register("bibliography_present")
def bibliography_present(ctx: CheckContext, check: VenueCheck) -> CheckResult:
    tex = ctx.main_tex
    if re.search(r"\\bibliography\{", tex) or "\\begin{thebibliography}" in tex:
        n = len(ctx.manuscript.references)
        return result(check, True, f"Reference list present ({n} entr{'y' if n == 1 else 'ies'}).")
    return result(check, False, "No reference list found.")


@register("anonymity")
def anonymity(ctx: CheckContext, check: VenueCheck) -> CheckResult:
    if not ctx.spec.content_rules.anonymous_submission:
        return result(check, True, "Not an anonymous version, so authors are shown.")
    tex = ctx.main_tex
    leaks = [a.name for a in ctx.manuscript.authors if a.name and a.name in tex]
    if leaks:
        return result(check, False, "Author names appear in the anonymized paper.", details=leaks)
    return result(check, True, "No author names found in the source.")


@register("manual")
def manual(ctx: CheckContext, check: VenueCheck) -> CheckResult:
    return CheckResult(check_id=check.id, type=check.type, status="manual_review", message=check.description)
