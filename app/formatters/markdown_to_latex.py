"""Convert Markdown inline syntax and block content to LaTeX."""

from __future__ import annotations

import html
import re

from app.parsers.text_utils import latex_escape

# Inline HTML that Markdown papers use; any other tag is dropped and its text kept.
HTML_STYLES = {"sup": "\\textsuperscript{%s}", "sub": "\\textsubscript{%s}", "b": "\\textbf{%s}",
               "strong": "\\textbf{%s}", "i": "\\emph{%s}", "em": "\\emph{%s}", "u": "\\underline{%s}",
               "small": "{\\small %s}"}
HTML_TAGS = "sup|sub|b|strong|i|em|u|small|code|kbd|a|span|mark|s|del|ins|font|abbr|cite|q"
HTML_DROP = r"div|p|center|span|font|figure|figcaption|section|br|hr|img"
TOKEN_RE = re.compile(
    r"(?P<code>`+)(?P<code_body>.+?)(?P=code)"
    # Pandoc's rule: $ opens math only before a non-space and closes only after one, not before a digit,
    # so "$2.48 per hour and $0.74" stays text.
    r"|(?<![\\$])\$(?P<math>[^\s$](?:[^$\n]*?[^\s\\$])?)\$(?![\d$])"
    r"|<!--.*?-->"
    r"|<(?P<html>" + HTML_TAGS + r")\b(?P<html_attrs>[^<>]*)>(?P<html_body>.*?)</(?P=html)\s*>"
    r"|<img\b(?P<img_attrs>[^<>]*)>"
    r"|(?P<html_other></?(?:" + HTML_DROP + r")\b[^<>]*>)"
    r"|\^\[(?P<note>(?:[^\[\]]|\[[^\[\]]*\])+)\]"
    r"|\[(?P<cites>[^\[\]@]*(?<![\w.])-?@[\w:.\-/+]+[^\[\]]*)\](?!\()"
    r"|!\[(?P<img_alt>[^\]]*)\]\((?P<img_src>[^)]+)\)"
    r"|\[(?P<link_text>[^\]]+)\]\((?P<link_url>[^)\s]+)\)"
    r"|(?P<texcmd>\\(?:cite[a-zA-Z]*|ref|eqref|autoref|cref|Cref|label|url|footnote)\*?(?:\[[^\]]*\])?\{[^{}]*\})"
    r"|(?P<bold>\*\*|__)(?P<bold_body>.+?)(?P=bold)"
    r"|(?<![\w*])(?P<em>[*_])(?P<em_body>[^*_\s](?:.*?[^*_\s])?)(?P=em)(?![\w*])"
    r"|(?<![\w@])@(?P<xref>(?:fig|tbl|tab|eq|sec):[\w:.\-]*\w)"
    r"|<(?P<auto_url>https?://[^>\s]+)>"
)
NATBIB_RE = re.compile(r"\\(citep|citet|citealp|citealt|citeauthor|citeyear|parencite|textcite|autocite|footcite|Citep|Citet)\*?((?:\[[^\]]*\]){0,2})\{")
CITE_ITEM_RE = re.compile(r"^(?P<prefix>[^@]*?)-?@(?P<key>[\w:.\-/+]*\w)\.?\s*,?\s*(?P<locator>.*)$")


def _citation(group: str) -> str:
    """Pandoc citations: [@a; @b], [@a, @b], [@a, p. 4], [see @a, sec. 2]. A locator becomes \\cite[p.~4]{a}."""
    items = [CITE_ITEM_RE.match(part.strip()) for part in re.split(r";|,(?=\s*-?@)", group)]
    if not all(items):  # e.g. an e-mail address in brackets: keep the text
        return latex_escape("[" + group + "]")
    prefix = items[0]["prefix"].strip()
    lead = latex_escape(prefix) + "~" if prefix else ""
    if not any(item["locator"].strip() for item in items):
        return lead + "\\cite{" + ",".join(item["key"] for item in items) + "}"
    cites = []
    for item in items:
        locator = re.sub(r"\s+", "~", latex_escape(item["locator"].strip()))
        cites.append(f"\\cite[{locator}]{{{item['key']}}}" if locator else f"\\cite{{{item['key']}}}")
    return lead + ", ".join(cites)


def html_attr(attrs: str, name: str) -> str:
    m = re.search(name + r"""\s*=\s*["']([^"']*)["']""", attrs, re.I)
    return html.unescape(m.group(1)) if m else ""


def _plain(text: str) -> str:
    """Escape plain text; HTML entities such as &amp; or &nbsp; become their characters first."""
    text = re.sub(r"&(#\d+|#x[0-9a-fA-F]+|[A-Za-z]+);", lambda m: html.unescape(m.group(0)), text)
    return latex_escape(text.replace("\u00a0", " "))


def _html(m: re.Match) -> str:
    tag, body = m.group("html").lower(), m.group("html_body")
    if tag in {"code", "kbd"}:
        return "\\texttt{" + _plain(body) + "}"
    if tag == "a" and (href := html_attr(m.group("html_attrs"), "href")):
        return inline_md(body) + "\\footnote{\\url{" + href + "}}"
    return HTML_STYLES.get(tag, "%s") % inline_md(body)


QUOTE_RE = re.compile(r"(`+).+?\1|(?<![\\$])\$[^$\n]+\$|\]\([^)]*\)|<[^<>]*>|\"")


def smart_quotes(text: str) -> str:
    """Straight double quotes become curly ones, as Pandoc does, except inside code, math, links and tags."""
    def repl(m: re.Match) -> str:
        if m.group(0) != '"':
            return m.group(0)
        before = text[m.start() - 1] if m.start() else " "
        return "\u201c" if before.isspace() or before in "([{/\u2014-" else "\u201d"

    return QUOTE_RE.sub(repl, text)


def inline_md(text: str) -> str:
    """Convert inline Markdown to LaTeX, escaping everything else."""
    text = smart_quotes(text)
    out: list[str] = []
    pos = 0
    for m in TOKEN_RE.finditer(text):
        out.append(_plain(text[pos:m.start()]))
        pos = m.end()
        if m.group("code") is not None:
            body = m.group("code_body").strip()
            out.append("\\texttt{" + latex_escape(body) + "}")
        elif m.group("math") is not None:
            out.append("$" + m.group("math") + "$")
        elif m.group("html") is not None:
            out.append(_html(m))
        elif m.group("img_attrs") is not None:
            out.append(_plain(html_attr(m.group("img_attrs"), "alt")))
        elif m.group("html_other") is not None:
            out.append(" " if m.group("html_other").lower().startswith("<br") else "")
        elif m.group("note") is not None:
            out.append("\\footnote{" + inline_md(m.group("note")) + "}")
        elif m.group("cites") is not None:
            out.append(_citation(m.group("cites")))
        elif m.group("img_src") is not None:
            out.append(latex_escape(m.group("img_alt")))
        elif m.group("link_url") is not None:
            out.append(inline_md(m.group("link_text")) + "\\footnote{\\url{" + m.group("link_url") + "}}")
        elif m.group("texcmd") is not None:
            out.append(m.group("texcmd"))
        elif m.group("bold") is not None:
            out.append("\\textbf{" + inline_md(m.group("bold_body")) + "}")
        elif m.group("em") is not None:
            out.append("\\emph{" + inline_md(m.group("em_body")) + "}")
        elif m.group("xref") is not None:
            label = m.group("xref")
            prefix = {"fig": "Fig.~", "tbl": "Table~", "tab": "Table~", "eq": "Eq.~", "sec": "Section~"}[label.split(":")[0]]
            before = text[:m.start()]
            if re.search(r"(fig\.|figures?|tables?|eqs?\.|equations?|sections?|sec\.)\s*$", before, re.I):
                # The author already wrote "Figure @fig:x": keep their word, just tie it to the number.
                if out and out[-1].endswith(" "):
                    out[-1] = out[-1][:-1] + "~"
                prefix = ""
            out.append(prefix + "\\ref{" + label + "}")
        elif m.group("auto_url") is not None:
            out.append("\\url{" + m.group("auto_url") + "}")
    out.append(_plain(text[pos:]))
    return "".join(out)


def surname(person: str) -> str:
    """ "Lee, Ana" and "Ana Lee" give "Lee"; "{van der Berg}, Jan" gives "van der Berg"."""
    person = person.strip()
    last = person.split(",")[0] if "," in person else (re.findall(r"\{[^{}]*\}|\S+", person) or [""])[-1]
    return last.strip().strip("{}")


def cited_names(references) -> dict[str, tuple[str, str]]:
    """Each BibTeX key's authors as a sentence names them ("Lee", "Lee and Kim", "Lee et al.") and its year."""
    names = {}
    for ref in references:
        people = [surname(p) for p in re.split(r"\s+and\s+", ref.fields.get("author", "")) if p.strip()]
        if not people:
            continue
        if len(people) > 2 or people[-1] == "others":
            names[ref.key] = (f"{people[0]} et al.", ref.fields.get("year", ""))
        else:
            names[ref.key] = (" and ".join(people), ref.fields.get("year", ""))
    return names


TEXTUAL_RE = re.compile(r"\\(citet|Citet|textcite|citeauthor|Citeauthor|citeyear)\*?((?:\[[^\]]*\]){0,2})\{([^{}]*)\}")


def normalize_citations(latex: str, names: dict[str, tuple[str, str]] | None = None) -> str:
    """Map natbib/biblatex citation commands to plain \\cite, for classes without natbib (IEEEtran). A citation
    that names its authors keeps them: \\citet{lee20} becomes "Lee et al.~\\cite{lee20}", \\citeyear{lee20} "2020"."""
    names = names or {}

    def textual(m: re.Match) -> str:
        keys = [key.strip() for key in m.group(3).split(",")]
        if not all(key in names for key in keys):
            return m.group(0)
        command, note = m.group(1).lower(), m.group(2) if m.group(2).count("[") == 1 else ""
        if command == "citeauthor":
            parts = [names[key][0] for key in keys]
        elif command == "citeyear":
            parts = [names[key][1] for key in keys]
        else:
            parts = [f"{names[key][0]}~\\cite{note if key == keys[-1] else ''}{{{key}}}" for key in keys]
        return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]

    latex = TEXTUAL_RE.sub(textual, latex)
    return NATBIB_RE.sub(lambda m: "\\cite" + (m.group(2) if m.group(2).count("[") == 1 else "") + "{", latex)


BIBLATEX_TO_NATBIB = {"parencite": "citep", "autocite": "citep", "footcite": "citep", "textcite": "citet"}


def natbib_citations(latex: str) -> str:
    """Map biblatex citation commands to natbib's."""
    return re.sub(r"\\(parencite|autocite|footcite|textcite)(?=[\[*{])",
                  lambda m: "\\" + BIBLATEX_TO_NATBIB[m.group(1)], latex)
