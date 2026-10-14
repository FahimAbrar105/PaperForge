"""Writing-style checks. They never change the paper: each lists what the author may want to fix, and none of
them changes whether the layout passed."""

from __future__ import annotations

import re

from app.agents.text_fixes import CAPTION, CODE, DISPLAY_MATH, FLOAT, NOT_A_VERB
from app.models.report import CheckResult
from app.models.venue import VenueCheck
from app.parsers.latex_parser import expand_macros, find_command, find_environment, latex_to_plain, read_group
from app.parsers.text_utils import normalize_space, word_count
from app.validators.registry import CheckContext, register, result

HEADING_RE = re.compile(r"\\(section|subsection|subsubsection)\*?\{((?:[^{}]|\{[^{}]*\})*)\}")
HEADING_LEVEL = {"section": 1, "subsection": 2, "subsubsection": 3}
CITATION = r"(?:\\cite\{[^{}]*\}|\[\d+(?:\s*(?:,|--|-)\s*\d+)*\])"
CITATIONS = rf"{CITATION}(?:\s*(?:,|--|-|and)\s*{CITATION})*"
# A citation that starts a clause and is followed by a verb, or names systems "such as [2]": "[3] shows", "[3]--[5]
# survey", "such as [2], [10] compile".
CITATION_AS_WORD_RE = re.compile(rf"(?:(?:^|[.!?;:]\s+|\n\s*)|\bsuch as\s+)({CITATIONS})\s+([a-z]+)")
MONTH_RE = re.compile(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2},?\s+)?\d{4}")
CONFERENCE_RE = re.compile(r"\b(Proc\.|Proceedings|Conf\.|Conference|Symp\.|Symposium|Workshop)", re.I)
LINKED_RE = re.compile(r"\b10\.\d{4,9}/|doi\.org/|aclanthology\.org/", re.I)
# Words that give away who wrote an anonymous paper: "our previous work [3]", "we previously showed", a grant.
SELF_REFERENCE_RE = re.compile(
    r"\b(?:our|my)\s+(?:own\s+)?(?:previous|prior|earlier|past)\s+(?:work|paper|study|system|publication|result)s?\b"
    r"|\bwe\s+(?:have\s+)?(?:previously|earlier)\s+(?:shown|showed|proposed|presented|introduced|described|reported)\b"
    r"|\b(?:supported|funded)\s+(?:in\s+part\s+)?by\b", re.I)
LINK_RE = re.compile(r"(?:https?://|www\.)[^\s{}\\]+|\b[\w.-]+\.github\.io\b[^\s{}\\]*"
                     r"|\b(?:github\.com|gitlab\.com|bitbucket\.org|huggingface\.co)/[^\s{}\\]+", re.I)
# Links that name a person or lab, or count who opens them.
PERSONAL_LINK_RE = re.compile(r"github\.com|gitlab\.com|bitbucket\.org|huggingface\.co|\.github\.io|sites\.google"
                              r"|/~|dropbox\.com|drive\.google|onedrive|1drv\.ms|bit\.ly", re.I)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
ABBREVIATION_RE = re.compile(r"(?<![\w\-/.])([A-Z][A-Z0-9]*[A-Z])s?(?![\w\-/])")
ROMAN_RE = re.compile(r"[IVXLC]+")
ROMAN_NUMBERS = {r: n for n, r in enumerate(["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII",
                                              "XIII", "XIV", "XV"], 1)}
WELL_KNOWN = {"CPU", "GPU", "RAM", "ID", "PDF", "URL", "HTTP", "HTTPS", "TCP", "UDP", "IP", "DNS", "API", "USB",
              "IEEE", "ACM", "OK", "AI", "US", "USA", "UK", "EU", "PC", "OS", "SQL", "XML", "JSON", "HTML", "KB",
              "MB", "GB", "TB", "PB", "DNA", "RNA", "LED", "LCD", "GPS", "CEO", "FAQ", "LTE", "WIFI", "SSD"}
COUNTRIES = {
    "usa", "u.s.a.", "united states", "us", "uk", "u.k.", "united kingdom", "england", "scotland", "wales", "ireland",
    "canada", "mexico", "brazil", "argentina", "chile", "colombia", "peru", "germany", "france", "italy", "spain",
    "portugal", "netherlands", "the netherlands", "belgium", "switzerland", "austria", "sweden", "norway",
    "denmark", "finland", "iceland", "poland", "czech republic", "czechia", "hungary", "greece", "turkey",
    "russia", "ukraine", "israel", "egypt", "nigeria", "kenya", "ghana", "south africa", "morocco", "ethiopia",
    "india", "pakistan", "bangladesh", "sri lanka", "nepal", "china", "p. r. china", "hong kong", "taiwan",
    "japan", "south korea", "korea", "singapore", "malaysia", "indonesia", "thailand", "vietnam", "philippines",
    "australia", "new zealand", "saudi arabia", "united arab emirates", "uae", "qatar", "iran", "iraq", "jordan",
    "lebanon", "romania", "bulgaria", "serbia", "croatia", "slovenia", "slovakia", "estonia", "latvia",
    "lithuania", "luxembourg", "cyprus", "malta"}
# British and American spellings of the same word: (British, American).
SPELLINGS = [("colour", "color"), ("behaviour", "behavior"), ("favour", "favor"), ("labour", "labor"),
             ("neighbour", "neighbor"), ("honour", "honor"), ("flavour", "flavor"), ("endeavour", "endeavor"),
             ("centre", "center"), ("fibre", "fiber"), ("modelling", "modeling"), ("modelled", "modeled"),
             ("labelled", "labeled"), ("labelling", "labeling"), ("travelled", "traveled"),
             ("signalling", "signaling"), ("grey", "gray"), ("defence", "defense")]
IZE_STEMS = ["organi", "recogni", "reali", "summari", "optimi", "minimi", "maximi", "normali", "utili", "prioriti",
             "emphasi", "characteri", "generali", "speciali", "visuali", "paralleli", "initiali", "seriali",
             "synchroni", "standardi", "categori", "customi", "randomi", "tokeni", "virtuali"]
IZE_ENDINGS = r"(?:e|ed|es|ing|er|ers|ation|ations)\b"


def _text_part(tex: str) -> str:
    """The paper from its abstract (or title) to the reference list: the part the author wrote, without code."""
    start = next((i for i in (tex.find("\\begin{abstract}"), tex.find("\\maketitle"), tex.find("\\begin{document}"))
                  if i >= 0), 0)
    ends = [i for i in (tex.find("\\begin{thebibliography}"), tex.find("\\bibliography{")) if i > start]
    return CODE.sub(" ", tex[start:min(ends, default=len(tex))])


def _cited(latex: str, main_tex: str) -> str:
    """Citations in ``latex`` as the reader sees them: "[2], [3]", numbered the way the class numbers them (in
    the order of a typed reference list, otherwise in the order they are first cited)."""
    keys = re.findall(r"\\bibitem(?:\[[^\]]*\])?\{([^{}]*)\}", main_tex) or [
        key.strip() for m in re.finditer(r"\\cite\{([^{}]*)\}", _text_part(main_tex)) for key in m.group(1).split(",")]
    numbers = {key: n for n, key in enumerate(dict.fromkeys(keys), 1)}
    return re.sub(r"\\cite\{([^{}]*)\}", lambda m: ", ".join(f"[{numbers.get(k.strip(), k.strip())}]"
                                                           for k in m.group(1).split(",")), latex)


def _without_math(tex: str) -> str:
    tex = DISPLAY_MATH.sub(" ", tex)
    return re.sub(r"(?<!\\)\$(?:\\.|[^$\\])*\$|\\\(.*?\\\)", " x ", tex)  # "\$0.09" is a price, not math


def _plain(tex: str) -> str:
    return normalize_space(latex_to_plain(_without_math(tex)))


@register("lone_subsection")
def lone_subsection(ctx: CheckContext, check: VenueCheck) -> CheckResult:
    headings = [(HEADING_LEVEL[m.group(1)], normalize_space(latex_to_plain(m.group(2))))
                for m in HEADING_RE.finditer(_text_part(ctx.main_tex))]
    lone = []
    for i, (level, title) in enumerate(headings):
        children = []
        for child_level, child in headings[i + 1:]:
            if child_level <= level:
                break
            if child_level == level + 1:
                children.append(child)
        if len(children) == 1:
            lone.append(f"\"{title}\" has only \"{children[0]}\" under it.")
    if lone:
        return result(check, False, "A heading has a single subheading. Add a second one or merge it into the text "
                                    "above.", details=lone)
    return result(check, True, "No heading has a single subheading.")


@register("citation_as_noun")
def citation_as_noun(ctx: CheckContext, check: VenueCheck) -> CheckResult:
    found = []
    for m in CITATION_AS_WORD_RE.finditer(_without_math(_text_part(ctx.main_tex))):
        if m.group(2) not in NOT_A_VERB:
            cited = _cited(m.group(1), ctx.main_tex).replace("--", "\u2013")
            found.append(f"\"{normalize_space(cited)} {m.group(2)}\"")
    if found:
        return result(check, False, "Citation numbers are used as words. Write \"Smith et al. [3] show\" or \"as "
                                    "shown in [3]\" instead.", details=list(dict.fromkeys(found)))
    return result(check, True, "Citations are not used as words.")


def _initials_only(name: str) -> bool:
    """ "J. K. Smith" or "Smith, J.": the given names are only initials."""
    given = name.split(",", 1)[1] if "," in name else " ".join(name.split()[:-1])
    parts = given.replace("-", " ").split()
    return bool(parts) and all(re.fullmatch(r"[A-Z]\.?", p) for p in parts)


@register("reference_details")
def reference_details(ctx: CheckContext, check: VenueCheck) -> CheckResult:
    """What the venue's reference style asks for. params turn on each part: ``place`` (a conference's city and
    country), ``journal_month``, ``all_authors`` (no "et al."), ``full_first_names``, ``doi``, ``arxiv`` (cite the
    published version); ``example``, ``authors_rule`` and ``doi_rule`` say how the venue words it."""
    wants = check.params
    found: dict[str, list[str]] = {}
    for i, ref in enumerate(ctx.manuscript.references, 1):
        fields = {k.lower(): v for k, v in ref.fields.items()}
        if ref.origin == "bibtex":
            name = ref.key
            conference = ref.entry_type.lower() in {"inproceedings", "conference"}
            journal = ref.entry_type.lower() == "article"
            placed = bool(fields.get("address") or fields.get("location"))
            dated = bool(fields.get("month"))
            authors = re.split(r"\s+and\s+", fields.get("author", ""))
            shortened = "others" in authors
            initials = any(_initials_only(a) for a in authors if a != "others")
            linked = bool(fields.get("doi")) or bool(LINKED_RE.search(fields.get("url", "")))
            arxiv = "arxiv" in " ".join([fields.get("journal", ""), fields.get("eprint", ""), fields.get("url", ""),
                                         fields.get("archiveprefix", ""), fields.get("publisher", "")]).lower()
        else:
            raw = fields.get("raw", "")
            name = f"[{i}]"
            conference = bool(CONFERENCE_RE.search(raw))
            journal = not conference and bool(re.search(r"\bvol\.|\bVolume\b", raw))
            placed = any(re.search(rf"\b{re.escape(c)}\b", raw.lower()) for c in COUNTRIES)
            dated = bool(MONTH_RE.search(raw))
            shortened = bool(re.search(r"\bet\s+al\b", raw))
            initials = False
            linked = bool(LINKED_RE.search(raw))
            arxiv = "arxiv" in raw.lower()
        problems = [("place", conference and not placed), ("journal_month", journal and not dated),
                    ("all_authors", shortened), ("full_first_names", initials), ("doi", not linked and not arxiv),
                    ("arxiv", arxiv)]
        for part, missing in problems:
            if wants.get(part) and missing:
                found.setdefault(part, []).append(name)
    words = {
        "place": "Conference papers without the city and country: {} (this venue writes \"" +
                 wants.get("example", "in Proc. Name, City, Country, Year") + "\").",
        "journal_month": "Journal articles without the month: {} (for example \"vol. 5, no. 2, pp. 1\u201310, "
                         "Feb. 2024\").",
        "all_authors": "\"et al.\" instead of the author names: {} (" +
                       wants.get("authors_rule", "this venue lists every author") + ").",
        "full_first_names": "Authors given by initials only: {} (this venue prints full first names).",
        "doi": "No DOI: {} (" + wants.get("doi_rule", "this venue asks for a DOI where one exists") + ").",
        "arxiv": "arXiv preprints: {} (if a peer-reviewed version has appeared, cite that instead).",
    }
    details = [words[part].format(", ".join(found[part])) for part in words if part in found]
    if details:
        return result(check, False, "Some references are missing details this venue asks for.", details=details)
    return result(check, True, "References have the details this venue asks for.")


@register("undefined_abbreviations")
def undefined_abbreviations(ctx: CheckContext, check: VenueCheck) -> CheckResult:
    tex = re.sub(r"\\begin\{CCSXML\}.*?\\end\{CCSXML\}|\\ccsdesc(?:\[\d+\])?\{[^{}]*\}", " ", _text_part(ctx.main_tex),
                 flags=re.S)
    tex = re.sub(r"\b[A-Z][A-Za-z]?\d*(?=\$_|\\textsubscript)", " ", tex)  # CO$_2$ is a formula, not "CO"
    text = _plain(tex)
    defined = set(re.findall(r"\(\s*([A-Z][A-Za-z0-9]*[A-Z])s?\s*\)", text))
    used: dict[str, int] = {}
    for m in ABBREVIATION_RE.finditer(text):
        abbr = m.group(1)
        if abbr not in defined and abbr not in WELL_KNOWN and not ROMAN_RE.fullmatch(abbr):
            used[abbr] = used.get(abbr, 0) + 1
    if used:
        return result(check, False, "Abbreviations that are never spelled out: " + ", ".join(sorted(used)) + ". "
                      "Write the full term once, followed by the abbreviation in parentheses.")
    return result(check, True, "Every abbreviation is spelled out where it is first used.")


@register("stray_underscores")
def stray_underscores(ctx: CheckContext, check: VenueCheck) -> CheckResult:
    tex = re.sub(r"\\(url|path|href|texttt|nolinkurl|label|ref|eqref|cite)\{[^{}]*\}", " ",
                 _without_math(_text_part(ctx.main_tex)))
    words = [w for w in re.findall(r"\S*\\_\S*", tex)
             if not re.search(r"://|www\.|@|/", w)]
    found = sorted({latex_to_plain(w).strip(".,;:()") for w in words})
    if found:
        return result(check, False, "Underscores in the text: " + ", ".join(found) + ". If a subscript is meant, "
                      "write it as math, for example P4$_{16}$.")
    return result(check, True, "No stray underscores in the text.")


@register("abstract_min_length")
def abstract_min_length(ctx: CheckContext, check: VenueCheck) -> CheckResult:
    env = find_environment(ctx.main_tex, "abstract")
    words = word_count(env[2]) if env and "Abstract not found in the uploaded manuscript" not in env[2] else 0
    least = check.params.get("min_words", 150)
    if words and words < least:
        return result(check, False, f"The abstract has about {words} words; {least} to "
                                    f"{ctx.spec.content_rules.abstract_max_words or least} is usual for this venue.")
    return result(check, True, f"The abstract has about {words} words.")


def _names_a_country(affiliation: str) -> bool:
    parts = {normalize_space(p).strip(" .").lower() for p in re.split(r"[,\n]", affiliation)}
    return bool(parts & COUNTRIES) or bool(re.search(r",\s*[A-Z]{2}\b", affiliation))


@register("affiliation_location")
def affiliation_location(ctx: CheckContext, check: VenueCheck) -> CheckResult:
    if ctx.spec.content_rules.anonymous_submission:
        return result(check, True, "Not checked: the authors are hidden in this version.")
    missing = dict.fromkeys(a for author in ctx.manuscript.authors
                            if not _names_a_country(", ".join(author.affiliations)) for a in author.affiliations)
    if missing:
        example = check.params.get("example", "Department, Institution, City, Country")
        return result(check, False, f"Affiliations without a city and country. Write them as \"{example}\".",
                      details=list(missing))
    return result(check, True, "Every affiliation names its country.")


@register("spelling_consistency")
def spelling_consistency(ctx: CheckContext, check: VenueCheck) -> CheckResult:
    """British and American spellings mixed; with ``variety: american``, any British spelling."""
    text = _plain(_text_part(ctx.main_tex)).lower()
    british, american = set(), set()
    for uk, us in SPELLINGS:
        british |= set(re.findall(rf"\b{uk}\w*", text))
        american |= set(re.findall(rf"\b{us}(?:s|ed|ing|ings|ful|ly|al|ist|ists)?\b", text))
    for stem in IZE_STEMS:
        british |= set(re.findall(rf"\b{stem}s{IZE_ENDINGS}", text))
        american |= set(re.findall(rf"\b{stem}z{IZE_ENDINGS}", text))
    british |= set(re.findall(r"\banalys(?:e|ed|ing)\b", text))  # "analyses" is also the plural of "analysis"
    american |= set(re.findall(r"\banalyz(?:e|ed|es|ing|er|ers)\b", text))
    if british and check.params.get("variety") == "american":
        return result(check, False, "This venue uses American spelling. British spellings found: " +
                      ", ".join(sorted(british)) + ".")
    if british and american:
        return result(check, False, "British and American spellings are mixed: " + ", ".join(sorted(british)) +
                      " (British) and " + ", ".join(sorted(american)) + " (American). Use one throughout.")
    return result(check, True, "Spelling is consistently " + ("British." if british else "American."))


def _quote(text: str, start: int, end: int) -> str:
    """The match with the words around it in its sentence, to show the author where it is."""
    before = re.search(r"(?:[^\s.!?]+[ \t]+){0,3}$", text[:start])[0]
    after = re.match(r"(?:[ \t]+[^\s.!?]+){0,4}[.!?]?", text[end:])[0]
    return f"\"{normalize_space(before + text[start:end] + after)}\""


@register("identifying_text")
def identifying_text(ctx: CheckContext, check: VenueCheck) -> CheckResult:
    if not ctx.spec.content_rules.anonymous_submission:
        return result(check, True, "Not checked: this version names its authors.")
    tex = _text_part(ctx.main_tex)
    text = latex_to_plain(_without_math(_cited(tex, ctx.main_tex)))
    found = [_quote(text, *m.span()) for m in SELF_REFERENCE_RE.finditer(text)]
    found += [f"Title note: \"{normalize_space(latex_to_plain(note))}\"" for note in
              re.findall(r"\\thanks\{((?:[^{}]|\{[^{}]*\})*)\}", _title(ctx))]  # printed under the title
    every_link = check.params.get("no_links")
    links = [m.group(0).rstrip(".,;:)") for m in LINK_RE.finditer(tex)
             if every_link or (PERSONAL_LINK_RE.search(m.group(0)) and "anonymous" not in m.group(0).lower())]
    found += [f"Link: {link}" for link in dict.fromkeys(links)
              if not any(link != other and link in other for other in links)]  # a link's text repeats its URL
    found += [f"Email address: {m.group(0)}" for m in EMAIL_RE.finditer(text)]
    if found:
        links = ("this venue allows no links in the review version (write \"code will be made publicly "
                 "available\")" if every_link else "link code only through an anonymous repository")
        return result(check, False, "The anonymous version may give away who wrote it. Cite your own work in the "
                                    f"third person (\"Lee et al. [3] showed\"), {links}, and leave grants and "
                                    "emails for the final version.",
                      details=list(dict.fromkeys(found)))
    return result(check, True, "No self-references, personal links or emails found.")


def _figures(tex: str) -> list[tuple[str, str]]:
    """Each captioned figure: (its first words, its LaTeX)."""
    figures = []
    for m in FLOAT.finditer(tex):
        caption = CAPTION.search(m.group(3))
        if m.group(1) == "figure" and caption:
            short = read_group(m.group(3), caption.end(), "[", "]")
            group = read_group(m.group(3), short[1] if short else caption.end())
            words = normalize_space(latex_to_plain(group[0] if group else "")).split()
            figures.append((" ".join(words[:6]) + ("..." if len(words) > 6 else ""), m.group(3)))
    return figures


@register("figure_descriptions")
def figure_descriptions(ctx: CheckContext, check: VenueCheck) -> CheckResult:
    missing = [f"Figure {n} (\"{title}\")" for n, (title, latex) in enumerate(_figures(ctx.main_tex), 1)
               if "\\Description" not in latex]
    if missing:
        return result(check, False, "Figures without a text description for readers who cannot see them. Add "
                                    "\\Description{...} inside each one, saying what the figure shows in a "
                                    "sentence or two (not the caption again).", details=missing)
    return result(check, True, "Every figure has a text description.")


@register("ccs_concepts")
def ccs_concepts(ctx: CheckContext, check: VenueCheck) -> CheckResult:
    if ctx.spec.content_rules.anonymous_submission:
        return result(check, True, "Not needed for review; add CCS concepts for the final version.")
    if "\\ccsdesc" in ctx.main_tex:
        return result(check, True, "CCS concepts are present.")
    return result(check, False, "No CCS concepts. Choose them at https://dl.acm.org/ccs, then paste the generated "
                                "CCSXML block and \\ccsdesc lines before \\maketitle in main.tex.")


@register("no_appendices")
def no_appendices(ctx: CheckContext, check: VenueCheck) -> CheckResult:
    titles = [normalize_space(latex_to_plain(s.title)) for s in ctx.manuscript.appendices]
    if titles:
        return result(check, False, "This venue wants appendices in a separate supplementary file, so the main paper "
                                    "ends with the references. Move these to the supplementary material:",
                      details=titles)
    return result(check, True, "No appendices in the main paper.")


@register("abstract_form")
def abstract_form(ctx: CheckContext, check: VenueCheck) -> CheckResult:
    """params: ``max_paragraphs``, ``no_citations``, ``no_footnotes``, ``no_math``, ``plain_text``."""
    env = find_environment(ctx.main_tex, "abstract")
    text = env[2].strip() if env else ""
    wants = check.params
    problems = []
    paragraphs = len([p for p in re.split(r"\n\s*\n|\\par\b", text) if p.strip()])
    if paragraphs > wants.get("max_paragraphs", paragraphs):
        problems.append(f"It has {paragraphs} paragraphs; this venue asks for at most {wants['max_paragraphs']}.")
    if wants.get("no_citations") and re.search(r"\\cite\w*\{|\[\d+(?:[,\u2013-]\s*\d+)*\]", text):
        problems.append("It cites references; the abstract should stand on its own.")
    if wants.get("no_footnotes") and "\\footnote" in text:
        problems.append("It has a footnote.")
    if wants.get("no_math") and (DISPLAY_MATH.search(text) or re.search(r"(?<!\\)\$|\\\(", text)):
        problems.append("It has math; write it in words.")
    markup = sorted(set(re.findall(r"\\(textbf|textit|emph|texttt|textsc|underline|url|href)\b", text)))
    if wants.get("plain_text") and markup:
        problems.append("It uses text formatting (" + ", ".join(f"\\{c}" for c in markup) + "); the abstract is "
                        "also copied as plain text, so keep it free of markup.")
    if problems:
        return result(check, False, "The abstract does not follow this venue's form.", details=problems)
    return result(check, True, "The abstract follows this venue's form.")


@register("figure_resolution")
def figure_resolution(ctx: CheckContext, check: VenueCheck) -> CheckResult:
    pdf = ctx.pdf_path
    if not pdf:
        return result(check, True, "Not checked: no PDF was produced.")
    import pymupdf as fitz

    least = check.params.get("min_dpi", 300)
    low = []
    with fitz.open(str(pdf)) as doc:
        for page in doc:
            for image in page.get_image_info():
                inches = (image["bbox"][2] - image["bbox"][0]) / 72
                if inches >= 0.5 and image["width"] / inches < least * 0.95:
                    low.append(f"Page {page.number + 1}: an image {inches:.1f} in wide at about "
                               f"{image['width'] / inches:.0f} dpi")
    if low:
        return result(check, False, f"Some images print at less than {least} dpi and may look blurry. Export them "
                                    f"at a higher resolution, or as vector graphics (PDF) for plots.", details=low)
    return result(check, True, f"Every image prints at {least} dpi or more.")


TITLE_CASE_LOWER = {"an", "the", "and", "but", "or", "nor", "for", "as", "at", "by", "in", "of", "on", "to", "via"}
MINOR_WORDS = {"a", "an", "the", "and", "but", "or", "nor", "for", "so", "yet", "as", "at", "by", "in", "of", "on",
               "to", "up", "via", "vs", "per", "with", "from", "into", "onto", "over", "than", "upon", "within",
               "without", "about", "across", "after", "against", "along", "among", "around", "before", "behind",
               "below", "beyond", "during", "for", "like", "near", "off", "past", "since", "through", "toward",
               "towards", "under", "until", "versus", "et", "al", "is", "be"}


def _case_problems(text: str, case: str) -> list[str]:
    """Words that break title case (a lowercase main word) or sentence case (a capitalized ordinary word)."""
    words = re.findall(r"(?<![\w/])[A-Za-z][A-Za-z'-]+(?![\w/])", text)  # not the "s" of "Gb/s"
    starts = {0} | {i + 1 for i, w in enumerate(words) if re.search(rf"\b{re.escape(w)}\s*:", text)}
    if case == "title":
        return [w for i, w in enumerate(words) if w.islower() and (i in starts or w not in MINOR_WORDS)]
    return [w for i, w in enumerate(words) if i not in starts and re.fullmatch(r"[A-Z][a-z]+", w)]


def _capitalized_minor_words(text: str) -> list[str]:
    """Short words that title case keeps lowercase inside a title: "Caching On the Edge" capitalizes "On"."""
    words = re.findall(r"(?<![\w/])[A-Za-z][A-Za-z'-]+(?![\w/])", text)
    starts = {0} | {i + 1 for i, w in enumerate(words) if re.search(rf"\b{re.escape(w)}\s*:", text)}
    return [w for i, w in enumerate(words[:-1]) if i not in starts and w.lower() in TITLE_CASE_LOWER and w.istitle()]


def _title(ctx: CheckContext) -> str:
    title = find_command(ctx.main_tex, "title")
    group = r"\{((?:[^{}]|\{[^{}]*\})*)\}"
    return re.sub(rf"\\texorpdfstring{group}{group}", r"\1", title[2]) if title else ""


@register("title_style")
def title_style(ctx: CheckContext, check: VenueCheck) -> CheckResult:
    """params: ``case`` (title), ``no_all_caps``, ``no_math``, ``no_line_breaks``, ``avoid_words``."""
    latex = _title(ctx)
    title = normalize_space(latex_to_plain(expand_macros(latex, ctx.manuscript.preamble_extras.macros)))
    wants = check.params
    problems = []
    words = re.findall(r"[A-Za-z]+", title)
    if wants.get("no_all_caps") and len(words) > 2 and sum(w.isupper() for w in words) > len(words) * 0.7:
        problems.append("It is in capital letters; write it in title case and keep capitals for acronyms.")
    elif wants.get("case") == "title" and (lower := _case_problems(title, "title")):
        problems.append("Title case capitalizes these words: " + ", ".join(dict.fromkeys(lower)) + ".")
    if wants.get("case") == "title" and (upper := _capitalized_minor_words(title)):
        problems.append("Title case keeps these short words lowercase: " + ", ".join(dict.fromkeys(upper)) + ".")
    if wants.get("no_math") and re.search(r"(?<!\\)\$|\\footnote|\\\(", latex):
        problems.append("It has math or a footnote; write it in words.")
    if wants.get("no_line_breaks") and "\\\\" in latex:
        problems.append("It has a forced line break (\\\\); let the class break the title.")
    avoided = [w for w in wants.get("avoid_words", []) if re.search(rf"\b{w}\b", title, re.I)]
    if avoided:
        problems.append("Avoid " + " and ".join(f"\"{w}\"" for w in avoided) + " in the title; say what is new "
                        "instead.")
    if problems:
        return result(check, False, f"The title \"{title}\" does not follow this venue's style.", details=problems)
    return result(check, True, "The title follows this venue's style.")


@register("heading_case")
def heading_case(ctx: CheckContext, check: VenueCheck) -> CheckResult:
    """params: ``case`` (title or sentence), ``max_level`` (3 allows \\subsubsection)."""
    case, deepest = check.params.get("case", "title"), check.params.get("max_level", 3)
    found = []
    for m in HEADING_RE.finditer(_text_part(ctx.main_tex)):
        title = normalize_space(latex_to_plain(m.group(2)))
        if HEADING_LEVEL[m.group(1)] > deepest:
            found.append(f"\"{title}\": this venue discourages third-level headings.")
        elif words := _case_problems(title, case):
            fix = "capitalize" if case == "title" else "lowercase (unless a name)"
            found.append(f"\"{title}\": {fix} " + ", ".join(dict.fromkeys(words)) + ".")
        elif case == "title" and (words := _capitalized_minor_words(title)):
            found.append(f"\"{title}\": lowercase " + ", ".join(dict.fromkeys(words)) + ".")
    if found:
        return result(check, False, f"Some headings do not follow this venue's style ({case} case).", details=found)
    return result(check, True, f"Headings are in {case} case.")


@register("numbered_equations")
def numbered_equations(ctx: CheckContext, check: VenueCheck) -> CheckResult:
    tex = _text_part(ctx.main_tex)
    found = []
    for m in [*DISPLAY_MATH.finditer(tex), *re.finditer(r"(?<!\\)\$\$(.+?)\$\$", tex, re.S)]:
        if m.re is not DISPLAY_MATH or m.group(4) is not None or m.group(2) or m.group(1) == "displaymath":
            headings = [normalize_space(latex_to_plain(h.group(2))) for h in HEADING_RE.finditer(tex, 0, m.start())]
            math = normalize_space(m.group(3) if m.re is DISPLAY_MATH and m.group(1) else m.group(m.lastindex))
            found.append(f"\"{math[:40]}{'...' if len(math) > 40 else ''}\"" +
                         (f" in \"{headings[-1]}\"" if headings else ""))
    if found:
        return result(check, False, "This venue numbers every displayed equation. Use the equation environment "
                                    "instead of equation*, \\[ \\] or displaymath for these:", details=found)
    return result(check, True, "Every displayed equation is numbered.")


TYPED_REFERENCE_RE = re.compile(r"(?<![\w\\])(Fig\.|Figure|Tab\.|Table)(?:\s|~)+(\d+|[IVX]+)\b(?![.,]\d)")


@register("typed_references")
def typed_references(ctx: CheckContext, check: VenueCheck) -> CheckResult:
    """Typed "Fig. 3" or "Table 4" with no such figure or table, and figures or tables without a caption."""
    tex = _text_part(ctx.main_tex)
    floats = [(m.group(1), m.group(3)) for m in FLOAT.finditer(tex)]
    counts = {env: sum(1 for kind, inner in floats if kind == env and CAPTION.search(inner)) for env in ("figure", "table")}
    found = []
    for m in TYPED_REFERENCE_RE.finditer(_without_math(tex)):
        env = "table" if m.group(1).startswith("Tab") else "figure"
        number = int(m.group(2)) if m.group(2).isdigit() else ROMAN_NUMBERS.get(m.group(2), 0)
        if number > counts[env]:
            found.append(f"\"{m.group(1)} {m.group(2)}\": the paper has {counts[env] or 'no'} captioned {env}"
                         f"{'s' if counts[env] != 1 else ''}.")
    for env in ("figure", "table"):
        if missing := sum(1 for kind, inner in floats if kind == env and not CAPTION.search(inner)):
            found.append(f"{missing} {env}(s) without a caption: a reader cannot refer to {'it' if missing == 1 else 'them'}.")
    if found:
        return result(check, False, "Some figure or table references do not match the paper's figures and tables.",
                      details=list(dict.fromkeys(found)))
    return result(check, True, "Every typed figure and table reference matches a captioned figure or table.")


@register("text_pattern")
def text_pattern(ctx: CheckContext, check: VenueCheck) -> CheckResult:
    """A venue rule written as a pattern in the venue file. params: ``pattern``, ``message``, ``scope`` (body,
    title, abstract or all), ``plain`` (search the text without LaTeX and math), ``ignore_case``,
    ``anonymous_only``, ``final_only``."""
    wants = check.params
    anonymous = ctx.spec.content_rules.anonymous_submission
    if (wants.get("anonymous_only") and not anonymous) or (wants.get("final_only") and anonymous):
        return result(check, True, "Not checked in this version.")
    scope = wants.get("scope", "body")
    abstract = find_environment(ctx.main_tex, "abstract")
    text = {"title": _title(ctx), "abstract": abstract[2] if abstract else "", "all": ctx.main_tex}.get(
        scope, _text_part(ctx.main_tex))
    if wants.get("plain"):
        text = _plain(text)
    pattern = re.compile(wants["pattern"], re.I if wants.get("ignore_case") else 0)
    found = list(dict.fromkeys(normalize_space(m.group(0)) for m in pattern.finditer(text)))
    if found:
        return result(check, False, wants.get("message", check.description), details=[f"\"{f}\"" for f in found[:10]])
    return result(check, True, check.description + ": yes.")
