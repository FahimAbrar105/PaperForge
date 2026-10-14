"""Deterministic LaTeX manuscript parser.

The body of a LaTeX paper is kept as raw LaTeX (it is already LaTeX), split into
sections. Title, authors, abstract, keywords, preamble packages/macros, figures,
tables, equations, citations and the bibliography are extracted so the
formatter can rebuild the document on the venue template.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from app.models.manuscript import (
    Author,
    Figure,
    ManuscriptStructure,
    PreambleExtras,
    Reference,
    Section,
    SourceInfo,
    Table,
    TextBlock,
    flatten_sections,
    nest_sections,
)
from app.parsers.text_utils import normalize_space

SECTION_LEVELS = {"section": 1, "subsection": 2, "subsubsection": 3, "paragraph": 4}
CITE_RE = re.compile(r"\\(?:no)?cite[a-zA-Z]*\*?(?:\[[^\]]*\]){0,2}\{([^}]*)\}")
INCLUDEGRAPHICS_RE = re.compile(r"\\includegraphics\*?(?:\[[^\]]*\])?\{([^}]*)\}")
HEADING_RE = re.compile(r"\\(section|subsection|subsubsection|paragraph)(\*?)\s*(\[[^\]]*\])?\s*\{")
LABEL_RE = re.compile(r"\\label\{([^}]+)\}")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
EMAIL_CMD = r"\\email\{((?:[^{}]|\{[^{}]*\})*)\}"
KEYWORD_LINE_RE = re.compile(
    r"^[ \t]*(?:\\noindent\s*)?(?:\\(?:textbf|textit|emph)\{)?\s*(?:Keywords|Key words|Index Terms)\s*"
    r"(?:[:.]|---|--)?\s*\}?\s*(?:[:.]|---|--)?\s*(.+?)\s*$",
    re.M | re.I,
)
# Where % is a plain character: verbatim environments, \verb|..|, \lstinline and URLs.
LITERAL_PERCENT_RE = re.compile(
    r"\\begin\{(verbatim\*?|Verbatim|lstlisting|minted)\}.*?\\end\{\1\}"
    r"|\\(?:verb\*?|lstinline(?:\[[^\]]*\])?)([^a-zA-Z\s{])[^\n]*?\2"
    r"|\\(?:url|href|lstinline(?:\[[^\]]*\])?)\{[^{}\n]*\}",
    re.S,
)
MAX_INCLUDE_DEPTH = 8


# --------------------------------------------------------------------------- helpers
def strip_comments(text: str) -> str:
    """Remove % comments, keeping escaped \\% and the % in URLs, \\verb and verbatim-like environments."""
    out = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and (literal := LITERAL_PERCENT_RE.match(text, i)):
            out.append(literal.group(0))
            i = literal.end()
        elif ch == "\\":
            out.append(text[i : i + 2])
            i += 2
        elif ch == "%":
            line_end = text.find("\n", i)
            i = line_end if line_end >= 0 else len(text)
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def read_group(text: str, start: int, open_ch: str = "{", close_ch: str = "}") -> tuple[str, int] | None:
    """Read a balanced group beginning at ``start`` (skipping whitespace). Returns (content, end_index)."""
    i = start
    while i < len(text) and text[i] in " \t\n":
        i += 1
    if i >= len(text) or text[i] != open_ch:
        return None
    depth = 0
    j = i
    while j < len(text):
        ch = text[j]
        if ch == "\\":
            j += 2
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return text[i + 1 : j], j + 1
        j += 1
    return None


def find_command(text: str, name: str, start: int = 0) -> tuple[int, str | None, str, int] | None:
    """Find ``\\name[opt]{arg}``. Returns (cmd_start, optional, argument, end)."""
    pattern = re.compile(r"\\" + re.escape(name) + r"\*?(?![a-zA-Z])")
    for m in pattern.finditer(text, start):
        pos = m.end()
        optional = None
        opt = read_group(text, pos, "[", "]")
        if opt:
            optional, pos = opt
        arg = read_group(text, pos)
        if arg:
            return m.start(), optional, arg[0], arg[1]
    return None


def find_environment(text: str, env: str, start: int = 0) -> tuple[int, int, str] | None:
    """Return (begin_index, end_index_after_end, inner_content) for the first ``env``."""
    begin = re.compile(r"\\begin\{" + re.escape(env) + r"\}")
    end = re.compile(r"\\end\{" + re.escape(env) + r"\}")
    m = begin.search(text, start)
    if not m:
        return None
    depth = 1
    pos = m.end()
    while depth:
        nb = begin.search(text, pos)
        ne = end.search(text, pos)
        if not ne:
            return None
        if nb and nb.start() < ne.start():
            depth += 1
            pos = nb.end()
        else:
            depth -= 1
            pos = ne.end()
            if depth == 0:
                return m.start(), ne.end(), text[m.end() : ne.start()]
    return None


def resolve_inputs(text: str, base_dir: Path, depth: int = 0, warnings: list[str] | None = None) -> str:
    """Inline \\input{}/\\include{} files found in the (flat) upload directory."""
    if warnings is None:
        warnings = []
    if depth > MAX_INCLUDE_DEPTH:
        warnings.append("Too many nested \\input files; stopped expanding.")
        return text

    def repl(m: re.Match) -> str:
        name = m.group(2).strip()
        basename = Path(name.replace("\\", "/")).name
        for candidate in (basename, f"{basename}.tex"):
            path = (base_dir / candidate).resolve()
            if path.parent == base_dir.resolve() and path.is_file() and path.suffix == ".tex":
                inner = strip_comments(path.read_text(encoding="utf-8", errors="replace"))
                return resolve_inputs(inner, base_dir, depth + 1, warnings)
        warnings.append(f"Included file '{name}' was not uploaded; its content is missing.")
        return m.group(0)

    return re.sub(r"\\(input|include)\{([^}]+)\}", repl, text)


ACCENT_MARKS = {"'": "\u0301", "`": "\u0300", "^": "\u0302", '"': "\u0308", "~": "\u0303", "=": "\u0304",
                ".": "\u0307", "c": "\u0327", "v": "\u030c", "u": "\u0306", "H": "\u030b", "k": "\u0328",
                "r": "\u030a", "d": "\u0323", "b": "\u0331"}
LETTER_COMMANDS = {"ss": "\u00df", "o": "\u00f8", "O": "\u00d8", "ae": "\u00e6", "AE": "\u00c6", "oe": "\u0153",
                   "OE": "\u0152", "aa": "\u00e5", "AA": "\u00c5", "l": "\u0142", "L": "\u0141", "i": "\u0131",
                   "j": "\u0237", "dh": "\u00f0", "DH": "\u00d0", "th": "\u00fe", "TH": "\u00de"}
# What latex_to_plain turns braces, ~, dashes, quotes and escaped symbols into; other commands become a space.
PLAIN_SYMBOLS = {"{": "", "}": "", "\\{": "{", "\\}": "}", "~": " ", "---": "\u2014", "--": "\u2013", "``": "\u201c",
                 "''": "\u201d", "\\textbackslash": "\\", "\\textasciitilde": "~", "\\textasciicircum": "^"}


def decode_latex_chars(text: str) -> str:
    """Turn LaTeX accents and escaped specials (M\\"{u}ller, Fran\\c{c}ois, AT\\&T) into plain Unicode."""
    def accent(m: re.Match) -> str:
        base = m.group(2) or m.group(3) or ""
        base = {"\\i": "i", "\\j": "j"}.get(base, base)
        return unicodedata.normalize("NFC", base + ACCENT_MARKS[m.group(1)])

    # \'e  \'{e}  \"{\i}: symbol accents may be followed directly by the letter.
    text = re.sub(r"\\(['`^\"~=.])\s*(?:\{\s*(\\[ij]|[A-Za-z])\s*\}|(\\[ij](?![A-Za-z])|[A-Za-z]))", accent, text)
    # \c{c}  \c c: letter accents need braces or a space.
    text = re.sub(r"\\([cvuHkrdb])(?:\s*\{\s*(\\[ij]|[A-Za-z])\s*\}|\s+([A-Za-z]))", accent, text)
    text = re.sub(r"\\(ss|ae|AE|oe|OE|aa|AA|dh|DH|th|TH|o|O|l|L|i|j)(?![A-Za-z])(?:\{\}|\s?)",
                  lambda m: LETTER_COMMANDS[m.group(1)], text)
    return re.sub(r"(?<!\\)\\([&%$#_])", r"\1", text)


def latex_to_plain(text: str) -> str:
    """Rough LaTeX -> plain text used for author names and word counts."""
    text = re.sub(r"\\thanks\{[^{}]*(\{[^{}]*\}[^{}]*)*\}", "", text)
    text = decode_latex_chars(text)
    text = re.sub(r"\\(texttt|textsf|textup|textmd|textnormal|url|href)\{([^{}]*)\}", r"\2", text)
    text = re.sub(r"\\(textbf|textit|emph|textsc|textrm|mbox|text)\{([^{}]*)\}", r"\2", text)
    text = re.sub(r"\\\\(\[[^\]]*\])?", "\n", text)
    text = re.sub(r"\\xspace(?![a-zA-Z])", "", text)
    # One pass, so the \ and ~ that \textbackslash and \textasciitilde give back stay as they are.
    return re.sub(r"\\[a-zA-Z]+\*?|\\[{}]|[{}~]|---?|``|''", lambda m: PLAIN_SYMBOLS.get(m.group(0), " "), text)


def expand_macros(text: str, macros: list[str]) -> str:
    """Replace argument-free user macros, so a title using ``\\newcommand{\\sys}{\\textsc{FlowJoin}}`` reads FlowJoin."""
    for macro in macros:
        m = re.match(r"\\(?:(?:new|renew|provide)command\*?\s*\{?\\([A-Za-z]+)\}?|def\s*\\([A-Za-z]+))\s*\{(.*)\}\s*$",
                     macro, re.S)
        if m:
            name, body = m.group(1) or m.group(2), m.group(3)
            text = re.sub(r"\\" + name + r"(?![A-Za-z])(\{\})?", lambda _: body, text)
    return text


def plain_title(m: ManuscriptStructure) -> str:
    return normalize_space(latex_to_plain(expand_macros(m.title, m.preamble_extras.macros)))


# --------------------------------------------------------------------------- metadata
def parse_packages(preamble: str) -> list[tuple[str, str | None]]:
    out = []
    for m in re.finditer(r"\\usepackage\s*(?:\[([^\]]*)\])?\s*\{([^}]+)\}", preamble):
        opts = m.group(1)
        for name in m.group(2).split(","):
            name = name.strip()
            if name:
                out.append((name, opts))
    return out


def parse_macros(preamble: str) -> list[str]:
    macros = []
    pattern = re.compile(
        r"\\(newcommand|renewcommand|providecommand|DeclareMathOperator|newtheorem|newenvironment|def|let|definecolor|newcolumntype|SetKwInput)\*?"
    )
    pos = 0
    while True:
        m = pattern.search(preamble, pos)
        if not m:
            break
        start = m.start()
        i = m.end()
        kind = m.group(1)
        if kind == "def":
            name_m = re.match(r"\s*\\[a-zA-Z@]+[^{]*", preamble[i:])
            if not name_m:
                pos = i
                continue
            i += name_m.end()
            body = read_group(preamble, i)
            if body:
                i = body[1]
        elif kind == "let":
            let_m = re.match(r"\s*\\[a-zA-Z@]+\s*=?\s*\\[a-zA-Z@]+", preamble[i:])
            i += let_m.end() if let_m else 0
        else:
            # read the argument groups: {name}, [n], [default], {body}, {end-body}
            for _ in range(6):
                g = read_group(preamble, i) or read_group(preamble, i, "[", "]")
                if not g:
                    break
                i = g[1]
        snippet = preamble[start:i].strip()
        if snippet and "@" not in snippet.split("{", 1)[0]:
            macros.append(snippet)
        pos = max(i, m.end())
    return macros


ACM_ADDRESS_PARTS = ("department", "institution", "city", "state", "country")


def acm_authors(tex: str) -> list[Author]:
    """Authors from acmart: ``\\author{Name} \\email{..} \\affiliation{\\institution{..} \\city{..} \\country{..}}``.
    Authors listed before one \\affiliation share it."""
    authors: list[Author] = []
    waiting: list[Author] = []
    pos = 0
    pattern = re.compile(r"\\(author|affiliation|email)(?![a-zA-Z])")
    while m := pattern.search(tex, pos):
        found = find_command(tex, m.group(1), m.start())
        if not found or found[0] != m.start():
            pos = m.end()
            continue
        pos = found[3]
        if m.group(1) == "author":
            for name in re.split(r"\\and\b", found[2]):
                if name := normalize_space(latex_to_plain(name)):
                    authors.append(Author(name=name))
                    waiting.append(authors[-1])
        elif m.group(1) == "email" and authors:
            authors[-1].email = authors[-1].email or normalize_space(latex_to_plain(found[2]))
        elif m.group(1) == "affiliation":
            parts = [normalize_space(latex_to_plain(part[2])) for name in ACM_ADDRESS_PARTS
                     if (part := find_command(found[2], name))]
            affiliation = ", ".join(p for p in parts if p)
            for author in waiting or authors[-1:]:
                author.affiliations.append(affiliation)
            waiting = []
    return authors


def parse_authors(author_tex: str, institute_tex: str = "") -> list[Author]:
    if "\\IEEEauthorblockN" in author_tex:
        return _ieee_authors(author_tex)
    if institute_tex:
        return _lncs_authors(author_tex, institute_tex)
    return _plain_authors(author_tex)


def _ieee_authors(tex: str) -> list[Author]:
    """Authors from IEEEtran's \\IEEEauthorblockN{names} \\IEEEauthorblockA{affiliation \\\\ email} pairs."""
    authors: list[Author] = []
    pos = 0
    while names := find_command(tex, "IEEEauthorblockN", pos):
        pos = names[3]
        lines: list[str] = []
        block = find_command(tex, "IEEEauthorblockA", pos)
        next_names = find_command(tex, "IEEEauthorblockN", pos)
        if block and (not next_names or block[0] < next_names[0]):
            lines = _plain_lines(block[2], r"\\\\")
            pos = block[3]
        email = next((m.group(0) for line in lines if (m := EMAIL_RE.search(line))), None)
        affiliations = [line for line in lines if not EMAIL_RE.search(line)]
        for name in re.split(r"\\and|,|\band\b", names[2]):
            if name := normalize_space(latex_to_plain(name)):
                authors.append(Author(name=name, affiliations=affiliations, email=email))
    return authors


def _plain_authors(tex: str) -> list[Author]:
    """Authors from article-style ``\\author{Name \\\\ Institution \\\\ City, Country \\\\ email \\and ...}``.

    The lines under a name make up one affiliation. When there are none, a \\thanks{Dept., University, email}
    footnote carries the affiliation; otherwise it is an author note, not an affiliation.
    """
    authors: list[Author] = []
    for chunk in re.split(r"\\and\b", tex, flags=re.I):  # ACL separates authors with \And and \AND
        notes = []
        while thanks := find_command(chunk, "thanks"):
            notes.append(thanks[2])
            chunk = chunk[: thanks[0]] + chunk[thanks[3] :]
        lines = _plain_lines(chunk, r"\\\\|\n")
        if len(lines) == 1:
            lines += [line for note in notes for line in _plain_lines(note, r"\\\\|\n")]
        if not lines:
            continue
        email = None
        address = []
        for line in lines[1:]:
            match = EMAIL_RE.search(line)
            if match and not email:
                email = match.group(0)
                line = normalize_space(line.replace(email, "").strip(" ,;"))
            if line:
                address.append(line)
        affiliations = [", ".join(address)] if address else []
        for name in re.split(r",?\s+and\s+|,\s*", lines[0]):
            if name.strip():
                authors.append(Author(name=name.strip(), affiliations=affiliations, email=email))
    return authors


def _lncs_authors(tex: str, institute_tex: str) -> list[Author]:
    """Authors from Springer LNCS: ``Name\\inst{1,2} \\and ...`` with ``\\institute{Univ. \\email{..} \\and ...}``."""
    institutes: list[tuple[str, list[str]]] = []  # (affiliation, emails) in \inst order
    for part in re.split(r"\\and\b", institute_tex):
        emails = [e for found in re.finditer(EMAIL_CMD, part) for e in _expand_emails(found.group(1))]
        lines = _plain_lines(re.sub(EMAIL_CMD, "", part), r"\\\\|\n")
        institutes.append((", ".join(lines), emails))
    authors = []
    for chunk in re.split(r"\\and\b", tex):
        marks = re.search(r"\\inst\{([^}]*)\}", chunk)
        numbers = [int(n) for n in re.findall(r"\d+", marks.group(1))] if marks else [1] * (len(institutes) == 1)
        name = normalize_space(latex_to_plain(re.sub(r"\\(inst|orcidID|thanks)\{(?:[^{}]|\{[^{}]*\})*\}", "", chunk)))
        if not name:
            continue
        mine = [institutes[n - 1] for n in numbers if 0 < n <= len(institutes)]
        emails = [e for _, found in mine for e in found]
        authors.append(Author(name=name, affiliations=[aff for aff, _ in mine if aff],
                              email=_email_for(name, emails)))
    return authors


def _expand_emails(tex: str) -> list[str]:
    """``\\{ann,bo\\}@uni.edu`` (one domain for several people) becomes ann@uni.edu and bo@uni.edu."""
    text = decode_latex_chars(tex).replace("\\{", "{").replace("\\}", "}")
    if shared := re.fullmatch(r"\s*\{([^{}]*)\}\s*(@\S+)\s*", text):
        return [user.strip() + shared.group(2) for user in shared.group(1).split(",") if user.strip()]
    return EMAIL_RE.findall(text)


def _email_for(name: str, emails: list[str]) -> str | None:
    """The address whose user part contains the author's first or last name (kmensah@... for Kwame Mensah)."""
    if len(emails) == 1:
        return emails[0]
    folded = unicodedata.normalize("NFKD", name.lower()).encode("ascii", "ignore").decode()
    parts = [p for p in re.split(r"[^a-z]+", folded) if len(p) > 2]
    for email in emails:
        user = email.split("@")[0].lower()
        if parts and (parts[-1] in user or parts[0] in user):
            return email
    return None


def _plain_lines(tex: str, separator: str) -> list[str]:
    """The non-empty plain-text lines of a LaTeX snippet split at ``separator``."""
    lines = (normalize_space(latex_to_plain(part)) for part in re.split(separator, tex))
    return [line for line in lines if line]


def parse_thebibliography(text: str) -> list[Reference]:
    refs = []
    for m in re.finditer(r"\\bibitem(?:\[[^\]]*\])?\{([^}]+)\}(.*?)(?=\\bibitem|\Z)", text, re.S):
        refs.append(Reference(key=m.group(1).strip(), entry_type="misc",
                              fields={"raw": m.group(2).strip()}, origin="thebibliography"))
    return refs


# --------------------------------------------------------------------------- body
def split_sections(body: str) -> tuple[str, list[Section]]:
    """Split raw LaTeX body into a section tree. Returns (preface_text, sections)."""
    headings: list[tuple[int, int, Section]] = []  # (where the heading starts, where its text starts, section)
    for m in HEADING_RE.finditer(body):
        group = read_group(body, m.end() - 1)
        if not group:
            continue
        title, end = group
        label = re.match(r"\s*\\label\{([^}]+)\}", body[end:])
        if label:
            end += label.end()
        star = "*" if m.group(2) else ""  # marker kept so the formatter emits \section*
        section = Section(title=star + title.strip(), level=SECTION_LEVELS[m.group(1)],
                          label=label.group(1) if label else None)
        headings.append((m.start(), end, section))

    next_starts = [start for start, _, _ in headings[1:]] + [len(body)]
    for (_, end, section), next_start in zip(headings, next_starts):
        content = body[end:next_start].strip()
        if content:
            section.blocks.append(TextBlock(kind="raw_latex", content=content, format="latex"))
    preface = body[: headings[0][0]] if headings else body
    return preface.strip(), nest_sections([section for _, _, section in headings])


def collect_figures(body: str) -> list[Figure]:
    figures: list[Figure] = []
    for _, _, inner, wide in _floats(body, "figure"):
        caption, label = _caption_and_label(inner)
        for g in INCLUDEGRAPHICS_RE.finditer(inner):
            figures.append(Figure(id=f"fig{len(figures) + 1}", file=g.group(1).strip(),
                                  caption=caption, label=label, wide=wide))
    # Graphics outside figure environments.
    known = {f.file for f in figures}
    for g in INCLUDEGRAPHICS_RE.finditer(body):
        file = g.group(1).strip()
        if file not in known:
            figures.append(Figure(id=f"fig{len(figures) + 1}", file=file))
            known.add(file)
    return figures


def collect_tables(body: str) -> list[Table]:
    tables: list[Table] = []
    for start, end, inner, wide in _floats(body, "table"):
        caption, label = _caption_and_label(inner)
        tables.append(Table(id=f"tab{len(tables) + 1}", caption=caption, label=label,
                            raw_latex=body[start:end], wide=wide))
    return tables


def _floats(body: str, env: str):
    """Yield (start, end, inner, wide) for every ``env`` and ``env*`` environment; ``env*`` is the wide one."""
    for name, wide in ((env, False), (env + "*", True)):
        pos = 0
        while found := find_environment(body, name, pos):
            start, pos, inner = found
            yield start, pos, inner, wide


def _caption_and_label(inner: str) -> tuple[str, str | None]:
    caption = find_command(inner, "caption")
    label = LABEL_RE.search(inner)
    return (caption[2].strip() if caption else ""), (label.group(1) if label else None)


def collect_citations(text: str) -> list[str]:
    keys: list[str] = []
    for m in CITE_RE.finditer(text):
        for key in m.group(1).split(","):
            key = key.strip()
            if key and key not in keys:
                keys.append(key)
    return keys


def choose_main_tex(paths: list[Path]) -> Path:
    def score(p: Path) -> tuple[int, int]:
        t = p.read_text(encoding="utf-8", errors="replace")
        return (("\\documentclass" in t) * 2 + ("\\begin{document}" in t), len(t))

    return max(paths, key=score)


# --------------------------------------------------------------------------- entry point
def parse_latex(main_path: Path) -> ManuscriptStructure:
    warnings: list[str] = []
    text = strip_comments(main_path.read_text(encoding="utf-8", errors="replace"))
    text = resolve_inputs(text, main_path.parent, warnings=warnings)

    doc = find_environment(text, "document")
    if doc:
        preamble, body = text[: doc[0]], doc[2]
    else:
        warnings.append("No \\begin{document} found; treating the whole file as the body.")
        preamble, body = "", text
    meta_zone = preamble + "\n" + body  # \title, \author and \abstract may sit in the preamble or the body

    title_cmd = find_command(meta_zone, "title")
    # \thanks{} in the title (a funding note) is kept: IEEEtran prints it as a footnote.
    title = title_cmd[2].strip() if title_cmd else ""
    author_cmd = find_command(meta_zone, "author")
    institute_cmd = find_command(meta_zone, "institute")
    authors = parse_authors(author_cmd[2], institute_cmd[2] if institute_cmd else "") if author_cmd else []
    if re.search(r"\\affiliation\s*\{[^{}]*\\institution", meta_zone):
        authors = acm_authors(meta_zone)
    # authblk's \affil{...} fills in authors that have no affiliation yet.
    for affil in re.finditer(r"\\affil(?:\[[^\]]*\])?\{([^}]*)\}", meta_zone):
        for a in authors:
            if not a.affiliations:
                a.affiliations.append(normalize_space(latex_to_plain(affil.group(1))))

    abstract = ""
    if found := find_environment(body, "abstract"):
        abstract = found[2].strip()
        body = body[: found[0]] + body[found[1] :]
    elif found := find_command(meta_zone, "abstract"):
        abstract = found[2].strip()

    keywords, body = _take_keywords(body, meta_zone)
    ccs, body = _take_ccs(body)
    if found := find_command(abstract, "keywords"):  # LNCS puts \keywords{} inside the abstract
        abstract = (abstract[: found[0]] + abstract[found[3] :]).strip()
    body = _remove_front_matter(body)
    # LNCS 2024+: \begin{credits} \subsubsection{\ackname} ... \subsubsection{\discintname} ... \end{credits}
    body = re.sub(r"\\(begin|end)\{credits\}", "", body)
    body = body.replace("{\\ackname}", "{Acknowledgments}").replace("{\\discintname}", "{Disclosure of Interests}")
    references, body = _take_bibliography(body)
    acks_environment, body = _take_acks_environment(body)
    body, appendices = _take_appendices(body)
    preface, sections = split_sections(body)
    acknowledgments = _take_acknowledgments(sections) or acks_environment
    if preface:
        sections.insert(0, Section(title="*", level=1,
                                   blocks=[TextBlock(kind="raw_latex", content=preface, format="latex")]))

    packages = [f"\\usepackage[{o}]{{{n}}}" if o else f"\\usepackage{{{n}}}" for n, o in parse_packages(preamble)]
    appendix_latex = "\n".join(b.content for s in flatten_sections(appendices) for b in s.blocks)

    confidence = 0.4
    confidence += 0.2 if title else 0
    confidence += 0.15 if abstract else 0
    confidence += 0.25 if sections else 0
    if not title:
        warnings.append("No \\title found.")
    if not abstract:
        warnings.append("No abstract found.")

    return ManuscriptStructure(
        source=SourceInfo(primary_file=main_path.name, format="tex", confidence=min(confidence, 1.0), warnings=warnings),
        title=title,
        authors=authors,
        abstract=abstract,
        keywords=keywords,
        sections=sections,
        figures=collect_figures(body + "\n" + appendix_latex),
        tables=collect_tables(body),
        acknowledgments=acknowledgments,
        ccs=ccs,
        appendices=appendices,
        references=references,
        citation_keys_used=collect_citations(text),
        preamble_extras=PreambleExtras(packages=packages, macros=parse_macros(preamble)),
        text_format="latex",
    )


def _take_keywords(body: str, meta_zone: str) -> tuple[list[str], str]:
    """Find the keywords and remove them from the body.

    Looks for a keywords environment, then a \\keywords{} command, then a plain line such as
    "\\noindent\\textbf{Keywords:} a, b" or "Index Terms---a, b" before the first section.
    """
    keywords: list[str] = []
    for env in ("IEEEkeywords", "keywords", "keyword"):
        if found := find_environment(body, env):
            keywords = _split_keywords(found[2], r"[,;]")
            body = body[: found[0]] + body[found[1] :]
            break
    if not keywords and (found := find_command(meta_zone, "keywords")):
        keywords = _split_keywords(found[2], r"[,;]|\\and\b|\\sep\b")
        body = body.replace(meta_zone[found[0] : found[3]], "")
    if not keywords and (line := KEYWORD_LINE_RE.search(body)):
        first_section = re.search(r"\\section\*?\{", body)
        if not first_section or line.start() < first_section.start():
            keywords = [k.rstrip(".") for k in _split_keywords(line.group(1), r"[,;]")]
            body = body[: line.start()] + body[line.end() :]
    return keywords, body


def _split_keywords(tex: str, separators: str) -> list[str]:
    return [k for part in re.split(separators, tex) if (k := normalize_space(latex_to_plain(part)))]


ACM_FRONT_MATTER = ("affiliation", "additionalaffiliation", "email", "orcid", "authornote", "authornotemark",
                    "titlenote", "subtitle", "acmConference", "acmYear", "copyrightyear", "setcopyright", "acmDOI",
                    "acmISBN", "acmBooktitle", "acmPrice", "acmSubmissionID", "acmJournal", "acmVolume",
                    "acmNumber", "acmArticle", "acmMonth", "settopmatter", "received", "authorsaddresses")


def _remove_front_matter(body: str) -> str:
    for cmd in ("title", "author", "date", "affil", "institute", "titlerunning", "authorrunning", "toctitle",
                "tocauthor", "IEEEspecialpapernotice", "IEEEpeerreviewmaketitle", *ACM_FRONT_MATTER):
        while found := find_command(body, cmd):
            body = body[: found[0]] + body[found[3] :]
    body = re.sub(r"\\renewcommand\{\\shortauthors\}\{[^{}]*\}", "", body)
    body = re.sub(r"\\begin\{teaserfigure\}", r"\\begin{figure*}[t]", body).replace("\\end{teaserfigure}", "\\end{figure*}")
    return re.sub(r"\\(maketitle|IEEEpeerreviewmaketitle|IEEEoverridecommandlockouts)\b", "", body)


def _take_ccs(body: str) -> tuple[str | None, str]:
    """ACM's CCS concepts: the CCSXML block and the \\ccsdesc lines, taken out of the body."""
    parts = []
    if found := find_environment(body, "CCSXML"):
        parts.append(body[found[0]:found[1]])
        body = body[: found[0]] + body[found[1] :]
    while found := find_command(body, "ccsdesc"):
        parts.append(body[found[0]:found[3]])
        body = body[: found[0]] + body[found[3] :]
    return "\n".join(parts) or None, body


def _take_bibliography(body: str) -> tuple[list[Reference], str]:
    """Drop \\bibliography commands (the .bib file is read separately) and take out a thebibliography list."""
    body = re.sub(r"\\bibliographystyle\{[^}]*\}|\\bibliography\{[^}]*\}", "", body)
    body = re.sub(r"\\printbibliography(\[[^\]]*\])?", "", body)
    found = find_environment(body, "thebibliography")
    if not found:
        return [], body
    return parse_thebibliography(found[2]), body[: found[0]] + body[found[1] :]


def _take_appendices(body: str) -> tuple[str, list[Section]]:
    """Split the body at \\appendix. Returns (body before it, appendix sections)."""
    m = re.search(r"\\appendix\b|\\appendices\b|\\begin\{appendices\}", body)
    if not m:
        return body, []
    _, appendices = split_sections(body[m.end() :].replace("\\end{appendices}", ""))
    return body[: m.start()], appendices


def _take_acks_environment(body: str) -> tuple[str | None, str]:
    """The text of an acks (acmart, IEEE) or ack environment, taken out of the body."""
    found = find_environment(body, "acks") or find_environment(body, "ack")
    if not found:
        return None, body
    return found[2].strip(), body[: found[0]] + body[found[1] :]


def _take_acknowledgments(sections: list[Section]) -> str | None:
    """Remove an "Acknowledgment(s)" section at any level and return its text."""
    acknowledgments = None
    for parent in [None, *flatten_sections(sections)]:  # LNCS papers often use \subsubsection*{Acknowledgements}
        siblings = sections if parent is None else parent.subsections
        for section in list(siblings):
            if section.title.lstrip("*").strip().lower().startswith("acknowledg"):
                acknowledgments = "\n\n".join(b.content for b in section.blocks)
                siblings.remove(section)
    return acknowledgments


def referenced_bib_files(main_path: Path) -> list[str]:
    text = strip_comments(main_path.read_text(encoding="utf-8", errors="replace"))
    names = []
    for m in re.finditer(r"\\bibliography\{([^}]+)\}|\\addbibresource\{([^}]+)\}", text):
        for n in (m.group(1) or m.group(2)).split(","):
            n = Path(n.strip()).name
            names.append(n if n.endswith(".bib") else f"{n}.bib")
    return names
