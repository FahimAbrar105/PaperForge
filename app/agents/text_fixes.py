"""Small corrections that style guides agree on, made by rule so they work in every agentic mode and without an
AI key: equations end with the punctuation their sentence needs, equations and figures are named in the venue's
style, footnote marks follow punctuation, captions sit where the venue puts them, and in author-year venues a
citation that is the subject of its sentence names the authors. Each change is written down, so the report can
say what changed and where."""

from __future__ import annotations

import re

from app.models.venue import ContentRules
from app.parsers.latex_parser import latex_to_plain, read_group
from app.parsers.text_utils import normalize_space

# "Eq. (2)", "Eqs. (2) and (3)", "Equation~\eqref{eq:x}", "Fig.~\ref{fig:a}", "Ref. [3]": a word, then numbers.
EQUATION_NUMBER = (r"(?:\(\d+\)|\\eqref\{[^{}]*\}|\(\\ref\{[^{}]*\}\)|\\ref\{[^{}]*\}"
                   r"|\d+(?!\w|\.\d|\s*[-+*/=<>^]))")  # "Eq. 2", but not "equation 2x + 1"
NUMBER = r"(?:\\ref\{[^{}]*\}|\d+)"
SECTION_NUMBER = r"(?:\\ref\{[^{}]*\}|\d+(?:\.\d+)*)"
CITATION_NUMBER = r"(?:\\cite\{[^{}]*\}|\[\d+\])"
REFERENCE_NUMBER = {"equation": EQUATION_NUMBER, "figure": NUMBER, "table": NUMBER, "section": SECTION_NUMBER,
                    "citation": CITATION_NUMBER}
REFERENCE_WORDS = {"equation": r"[Ee]qns?\.|[Ee]qs?\.|[Ee]quations?", "figure": r"[Ff]igs?\.|[Ff]igures?",
                   "table": r"[Tt]abs?\.|[Tt]ables?", "section": r"[Ss]ects?\.|[Ss]ecs?\.|[Ss]ections?|\u00a7",
                   "citation": r"[Rr]efs?\.|[Rr]eferences?"}
REFERENCE_RE = {kind: re.compile(rf"(?<![\w\\])({words})(?:\s|~)*({REFERENCE_NUMBER[kind]}"
                                 rf"(?:\s*(?:,|and|--|\u2013|to)\s*{REFERENCE_NUMBER[kind]})*)(?![\w.]\d)")
                for kind, words in REFERENCE_WORDS.items()}
EQUATION_REF = REFERENCE_RE["equation"]
# A word before a reference that IEEE writes without its noun: "the equations (1)--(3)" can't become "the (1)--(3)".
ARTICLE_BEFORE = re.compile(r"\b(?:the|a|an|this|these|those|that|our|their|its|all|each|such|same)(?:\s|~)*\Z",
                            re.I)
DISPLAY_MATH = re.compile(r"\\begin\{(equation|align|gather|multline|eqnarray|displaymath)(\*?)\}(.*?)\\end\{\1\2\}"
                          r"|(?<!\\)\\\[(.*?)\\\]", re.S)  # not the "\\[2pt]" of a table row
SUBEQUATIONS = re.compile(r"\\begin\{subequations\}.*?\\end\{subequations\}", re.S)
FLOAT = re.compile(r"\\begin\{(figure|table)(\*?)\}(.*?)\\end\{\1\2\}", re.S)
CAPTION = re.compile(r"\\caption(?![a-zA-Z])")
FLOAT_CONTENT = re.compile(r"\\begin\{(tabular|tabularx|tabular\*|adjustbox|minipage)\}|\\resizebox|\\scalebox"
                           r"|\\includegraphics|\\input\{|\\fbox")
HEADING = re.compile(r"\\(?:section|subsection|subsubsection|paragraph)\*?\{((?:[^{}]|\{[^{}]*\})*)\}")
# Text that is not prose: code and comments, then also file names, URLs, labels and typewriter text.
CODE = re.compile(r"\\begin\{(verbatim\*?|Verbatim\*?|BVerbatim|LVerbatim|lstlisting|minted|comment|alltt)\}.*?"
                  r"\\end\{\1\}|\\verb\*?([^\w\s*])[^\n]*?\2|\\lstinline(?:\[[^\]]*\])?(?:\{[^{}]*\}|([^\w\s{\[])[^\n]*?\3)"
                  r"|\\mintinline\{\w+\}(?:\{[^{}]*\}|([^\w\s{])[^\n]*?\4)|(?<!\\)%[^\n]*", re.S)
NOT_PROSE = re.compile(CODE.pattern + r"|\\(?:url|path|href|includegraphics|input|include|label|ref|eqref|pageref|cref"
                       r"|Cref|autoref|Autoref|texttt)\*?(?:\[[^\]]*\])?\{(?:[^{}]|\{[^{}]*\})*\}", re.S)
# What may follow an equation's last symbol: its label, tag, a final line break.
INNER_END = re.compile(r"\\end\{(?:split|aligned|alignedat|gathered)\}\s*\Z")
EQUATION_TAIL = re.compile(r"(?:\s|\\label\{[^{}]*\}|\\nonumber\b|\\notag\b|\\tag\*?\{[^{}]*\}|\\\\)*$")
SPACING_AT_END = re.compile(r"(?:\\[,;:!]|\\q?quad\b|~|\\right\.|[\s}])+$")
# Between an equation and the words after it: spacing, \noindent, a float placed there.
SKIPPED_AFTER = re.compile(r"(?:\s+|\\(?:noindent|indent|smallskip|medskip|bigskip)\b|\\vspace\*?\{[^{}]*\}"
                           r"|\\end\{subequations\}|\\begin\{(figure|table)(\*?)\}.*?\\end\{\1\2\})+", re.S)
# Words that carry the sentence on after an equation: "..., where x is the rate".
GOES_ON = re.compile(r"(where|wherein|whereas|which|while|with|and|but|so|i\.e\.|e\.g\.)(?![\w.])")
NEW_SENTENCE = re.compile(r"\Z|[A-Z]|\\(?:section|subsection|subsubsection|paragraph|item|end|par)\b")
SENTENCE_START = re.compile(r"(?:\A|[.!?]|\n\s*\n|\\(?:section|subsection|subsubsection|paragraph)\*?\{[^\n]*\}"
                            r"|\\end\{(?:figure|table)\*?\})"
                            r"(?:\s|\\label\{[^{}]*\}|\\end\{\w+\*?\}|\\\]|\})*\Z")
NOT_A_SENTENCE_END = re.compile(r"\b(?:cf|e\.g|i\.e|al|vs|resp|Fig|Figs|Sec|Secs|Tab|Thm)\.\s*\Z")
# Words after a citation that show it is not the subject of a verb: "[3] and [4]", "(Lee, 2020) for details".
NOT_A_VERB = {"and", "or", "for", "to", "in", "on", "of", "with", "which", "that", "as", "but", "where", "while",
              "by", "from", "at", "et", "the", "a", "an", "also"}
CITEP_SUBJECT = re.compile(r"\\citep((?:\[[^\]]*\]){0,2})\{([^{}]*)\}(?=\s+([a-z]+)\b)")
# "Lee et al.~\citep{lee20}" prints "Lee et al. (Lee et al., 2020)".
TYPED_AUTHORS = re.compile(r"([A-Z][\w'-]+)((?:\s|~)+et(?:\s|~)+al\.|\s+and\s+[A-Z][\w'-]+)?(?:\s|~)*"
                           r"\\citep\{([^{},]+)\}")
FOOTNOTE = re.compile(r"\s*\\footnote(?![a-zA-Z])")
CITATIONS_AS_SUBJECT = re.compile(rf"({CITATION_NUMBER}(?:\s*(?:,|and|--|\u2013)\s*{CITATION_NUMBER})*)(?=\s+([a-z]+)\b)")
ET_AL = re.compile(r"\bet\.(\s*|~)al\b\.?|\bet(\s+|~)al\b(?!\.)")
# ".25" needs its zero; not in lengths such as "\vspace{-.5em}" or "width=.5\linewidth".
NO_LEADING_ZERO = re.compile(r"(?<=[\s($=<>\[,])\.(\d+)(?![\w\\]|\.\d)")
SIZE_ARGUMENTS = re.compile(r"\\(?:includegraphics|resizebox|scalebox|vspace|hspace|setlength|addtolength)\*?"
                            r"(?:\[[^\]]*\])?(?:\{[^{}]*\})*")
CLEVEREF = re.compile(r"\\(cref|Cref|autoref|Autoref)\{([^{}]*)\}")
# Names of labels Paper Forge does not number itself, from the label's usual prefix ("thm:main").
LABEL_PREFIX_WORDS = {"thm": "Theorem", "lem": "Lemma", "def": "Definition", "cor": "Corollary", "prop": "Proposition",
                      "alg": "Algorithm", "rem": "Remark", "ex": "Example", "asm": "Assumption", "lst": "Listing"}
LABEL = re.compile(r"\\label\{([^{}]*)\}")
CITE = re.compile(r"\\cite\{([^{}]*)\}")


def _skipped(tex: str, pattern: re.Pattern = NOT_PROSE) -> list[tuple[int, int]]:
    return [m.span() for m in pattern.finditer(tex)]


def _inside(spans: list[tuple[int, int]], at: int) -> bool:
    return any(start <= at < end for start, end in spans)


def _display_math(tex: str):
    skipped = _skipped(tex, CODE)
    return (m for m in DISPLAY_MATH.finditer(tex) if not _inside(skipped, m.start()))


def _numbered_rows(m: re.Match) -> list[str]:
    """The rows of a display equation that print a number."""
    env, star = m.group(1), m.group(2)
    if not env or star or env == "displaymath":
        return []
    content = re.sub(r"\\begin\{(\w+\*?)\}.*?\\end\{\1\}", "", m.group(3), flags=re.S)  # a matrix's rows don't count
    rows = [content] if env in {"equation", "multline"} else [r for r in content.split("\\\\") if r.strip()]
    return [r for r in rows if not re.search(r"\\(nonumber|notag|tag)\b", r)]


SECTION_LABEL = re.compile(r"\\(section|subsection|subsubsection)(\*?)\{(?:[^{}]|\{[^{}]*\})*\}\s*(?:\\label\{([^{}]*)\})?")
ROMAN = [(10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]


def roman(n: int) -> str:
    text = ""
    for value, letters in ROMAN:
        while n >= value:
            text, n = text + letters, n - value
    return text


def section_number(counts: list[int], appendix: bool, ieee: bool) -> str:
    """ "2.1" (most venues), "II-A" (IEEE), "A.1" (an appendix)."""
    parts = [n for n in counts if n]
    if appendix:
        return ".".join([chr(64 + parts[0]), *map(str, parts[1:])])
    if ieee:
        return roman(parts[0]) + ("-" + chr(64 + parts[1]) if len(parts) > 1 else "") + "".join(map(str, parts[2:]))
    return ".".join(map(str, parts))


def equation_numbers(tex: str) -> list[list[str]]:
    """The numbers each display equation prints, in reading order: "3", or "4a" and "4b" inside subequations."""
    groups = [m.span() for m in SUBEQUATIONS.finditer(tex)]
    numbers, count, group, letter = [], 0, None, 0
    for m in _display_math(tex):
        inside = next((g for g in groups if g[0] <= m.start() < g[1]), None)
        if inside and inside != group:
            count, group, letter = count + 1, inside, 0
        printed = []
        for _ in _numbered_rows(m):
            if inside:
                letter += 1
                printed.append(f"{count}{chr(96 + letter)}")
            else:
                count += 1
                printed.append(str(count))
        numbers.append(printed)
    return numbers


def reference_numbers(chunks: list[str], appendices: int = 0, ieee: bool = False
                      ) -> tuple[dict[str, str], dict[str, str]]:
    """The number each label of an equation, figure, table or section prints with, and the label's kind. Typed
    numbers and citations are looked up too: "table 2" and "section 3.1" give what the venue prints for them,
    "cite key" the citation's number. ``appendices``: how many of the last chunks are appendices; ``ieee``:
    tables and sections print in Roman numerals."""
    tex = "\n".join(chunks)
    numbers, kinds = {}, {}

    def add(label: str, number: str, kind: str) -> None:
        numbers[label], kinds[label] = number, kind

    for m, printed in zip(_display_math(tex), equation_numbers(tex)):
        for row, number in zip(_numbered_rows(m), printed):
            for label in LABEL.findall(row):
                add(label, number, "equation")
    for env in ("figure", "table"):
        floats = [m.group(3) for m in FLOAT.finditer(tex) if m.group(1) == env and CAPTION.search(m.group(3))]
        for number, inner in enumerate(floats, 1):
            shown = roman(number) if ieee and env == "table" else str(number)
            numbers[f"{env} {number}"] = shown
            for label in LABEL.findall(inner):
                add(label, shown, env)
    counts = [0, 0, 0]
    for i, chunk in enumerate(chunks):
        appendix = i >= len(chunks) - appendices
        if i == len(chunks) - appendices:
            counts = [0, 0, 0]
        for m in SECTION_LABEL.finditer(chunk):
            if m.group(2):
                continue
            level = ["section", "subsection", "subsubsection"].index(m.group(1))
            counts[level:] = [counts[level] + 1] + [0] * (2 - level)
            shown = section_number(counts, appendix, ieee)
            if not appendix:
                numbers["section " + ".".join(str(n) for n in counts if n)] = shown
            if m.group(3):
                add(m.group(3), shown, "appendix" if appendix else "section")
    keys = dict.fromkeys(key.strip() for m in CITE.finditer(tex) for key in m.group(1).split(","))
    numbers.update((f"cite {key}", str(n)) for n, key in enumerate(keys, 1))
    return numbers, kinds


def needed_mark(after: str) -> tuple[str, str] | None:
    """The punctuation an equation needs, judged by the words after it, and why: a comma when the sentence goes on
    ("where ..."), a period when a new sentence starts. None when the words don't tell."""
    skip = SKIPPED_AFTER.match(after)
    after = after[skip.end():] if skip else after
    if goes_on := GOES_ON.match(after):
        return ",", f"the sentence goes on with \"{goes_on.group(1)}\""
    if NEW_SENTENCE.match(after):
        return ".", "its sentence ends there"
    return None


def starts_sentence(before: str) -> bool:
    return bool(SENTENCE_START.search(before)) and not NOT_A_SENTENCE_END.search(before)


def plural(word: str) -> str:
    if word.endswith("ix"):
        return word[:-2] + "ices"
    return word[:-1] + "s." if word.endswith(".") else word + "s"


def words_around(before: str, after: str) -> tuple[str, str]:
    """Up to two plain words on each side, to quote a change in context."""
    return (re.search(r"(?:[A-Za-z][\w'-]*\s+){0,2}(?:[A-Za-z][\w'-]*)?$", before)[0],
            re.match(r"(?:\s+[A-Za-z][\w'-]*\.?){0,2}", after)[0])


class TextFixer:
    """``names``: each BibTeX key's authors and year as a sentence cites them; ``packages``: what the venue's class
    loads; ``reference_list``: the keys of a typed reference list, in its order."""

    def __init__(self, rules: ContentRules, chunks: list[str], author_year: bool = False, appendices: int = 0,
                 names: dict[str, tuple[str, str]] | None = None, packages: list[str] = (),
                 reference_list: list[str] = ()) -> None:
        self.words = rules.reference_words
        self.table_caption = rules.table_caption
        self.leading_zero = rules.leading_zero
        self.roman = rules.roman_numbers
        self.author_year = author_year
        self.names = names or {}
        self.packages = set(packages)
        self.numbers, self.kinds = reference_numbers(chunks, appendices, rules.roman_numbers)
        self.numbers.update((f"cite {key}", str(n)) for n, key in enumerate(reference_list, 1))
        self.equations = equation_numbers("\n".join(chunks))
        self.maths_seen = 0
        self.place = ""  # where the text being fixed is, when it has no heading
        self.changes: list[str] = []
        self.found: list[tuple[int, str]] = []  # this chunk's changes, by where they are

    def fix_abstract(self, abstract: str) -> str:
        """The abstract has no equations, floats or references to fix, only its "et al." and its numbers."""
        self.place = " in the abstract"
        abstract = self.spell_et_al(abstract)
        if self.leading_zero:
            abstract = self.add_leading_zeros(abstract)
        self.place = ""
        return self.record(abstract)

    def fix(self, chunk: str) -> str:
        """``chunk`` is one top-level section of the paper; call it for each one in reading order."""
        chunk = self.name_cleveref(chunk)
        chunk = self.punctuate_equations(chunk)
        for kind in self.words:
            chunk = self.name_references(chunk, kind)
        if self.words.get("citation", ("", ""))[1]:
            chunk = self.name_cited_subjects(chunk)
        chunk = self.move_footnote_marks(chunk)
        chunk = self.place_captions(chunk)
        chunk = self.spell_et_al(chunk)
        if self.leading_zero:
            chunk = self.add_leading_zeros(chunk)
        if self.author_year:
            chunk = self.name_cited_authors(chunk)
        return self.record(chunk)

    def record(self, text: str) -> str:
        self.changes += [change for _, change in sorted(self.found)]
        self.found = []
        return text

    def note(self, chunk: str, at: int, text: str) -> None:
        self.found.append((at, text.replace("{where}", self.where(chunk, at))))

    def punctuate_equations(self, chunk: str) -> str:
        inserts = []
        floats = [m.span() for m in FLOAT.finditer(chunk)]  # an equation in a figure is not part of a sentence
        for m in _display_math(chunk):
            numbers = self.equations[self.maths_seen] if self.maths_seen < len(self.equations) else []
            self.maths_seen += 1
            group = 3 if m.group(1) else 4
            content = m.group(group)
            body = content[:EQUATION_TAIL.search(content).start()]
            if inner := INNER_END.search(body):  # the mark ends the last row of an aligned block
                body = body[:inner.start()]
                body = body[:EQUATION_TAIL.search(body).start()]
            last = SPACING_AT_END.sub("", body)
            mark = needed_mark(chunk[m.end():])
            if not last or last[-1] in ",.;:!?" or not mark or _inside(floats, m.start()):
                continue
            inserts.append((m.start(group) + len(body), mark[0]))
            name = f"Equation ({numbers[-1]})" if numbers else "An unnumbered equation"
            what = "a comma" if mark[0] == "," else "a period"
            self.note(chunk, m.start(), f"{name}{{where}}: added {what} at its end, as {mark[1]}.")
        for at, mark in reversed(inserts):
            chunk = chunk[:at] + mark + chunk[at:]
        return chunk

    def name_references(self, chunk: str, kind: str) -> str:
        """Equations and figures are named as the venue asks: IEEE writes "(2)" and "Fig. 1", most venues "Eq. (2)"
        and "Figure 1". The venue file gives the word inside a sentence and the word that starts one."""
        inside, at_start = self.words[kind]
        skipped = _skipped(chunk)

        def rename(m: re.Match) -> str:
            if _inside(skipped, m.start()):
                return m.group(0)
            numbers = self.printed_numbers(m.group(2), kind)
            before = chunk[:m.start()]
            first = starts_sentence(before)
            word = at_start if first else inside
            if not word and ARTICLE_BEFORE.search(before):
                return m.group(0)
            count = len(re.findall(REFERENCE_NUMBER[kind], numbers)) + numbers.count(",") * (kind == "citation")
            if word and (m.group(1).endswith(("s", "s.")) or count > 1):
                word = plural(word)
            new = f"{word}~{numbers}" if word else numbers
            old_text, new_text = self.readable(m.group(0)), self.readable(new)
            if old_text == new_text:
                return m.group(0)
            left, right = words_around("" if first else before, chunk[m.end():])
            old_text, new_text = (normalize_space(left + t + right) for t in (old_text, new_text))
            self.note(chunk, m.start(), f"\"{old_text}\" is now \"{new_text}\"{{where}}.")
            return new

        return REFERENCE_RE[kind].sub(rename, chunk)

    def printed_numbers(self, numbers: str, kind: str) -> str:
        """Typed numbers as the venue prints them: "Eq. 2" refers to "(2)", and IEEE's "Table 2" to "Table II"."""
        if kind == "equation":
            numbers = re.sub(r"(?<!\()\\ref\{", r"\\eqref{", numbers)
            return re.sub(r"(?<![\w({])(\d+)(?![\w)}])", r"(\1)", numbers)
        if kind in ("table", "section") and self.roman:
            return re.sub(r"\\ref\{[^{}]*\}|(\d+(?:\.\d+)*)", lambda n: self.numbers.get(f"{kind} {n.group(1)}", n.group(1))
                          if n.group(1) else n.group(0), numbers)
        return numbers

    def name_cleveref(self, chunk: str) -> str:
        """\\cref and \\autoref write the reference's word themselves. Written out in this venue's words: the venue's
        class may not load cleveref, and IEEE writes "Fig. 1" where \\autoref prints "Figure 1"."""
        skipped = _skipped(chunk, CODE)
        defaults = ContentRules().reference_words

        def rename(m: re.Match) -> str:
            command, labels = m.group(1), [label.strip() for label in m.group(2).split(",")]
            kinds = {self.kinds.get(label) for label in labels}
            kind = kinds.pop() if len(kinds) == 1 else None
            keep = (command.lower() == "cref" and "cleveref" in self.packages
                    or command.lower() == "autoref" and "hyperref" in self.packages and kind not in self.words)
            if _inside(skipped, m.start()) or keep:
                return m.group(0)
            before = chunk[:m.start()]
            first = command[0].isupper() or starts_sentence(before)
            prefixes = {label.split(":")[0] for label in labels}
            if kind in defaults:
                inside, at_start = self.words.get(kind) or defaults[kind]
                word = at_start if first else inside or (at_start.lower() if ARTICLE_BEFORE.search(before) else "")
            else:
                word = "Appendix" if kind == "appendix" else LABEL_PREFIX_WORDS.get(prefixes.pop(), "") if len(
                    prefixes) == 1 else ""
            ref = "\\eqref" if kind == "equation" else "\\ref"
            refs = [f"{ref}{{{label}}}" for label in labels]
            numbers = refs[0] if len(refs) == 1 else ", ".join(refs[:-1]) + (", and " if len(refs) > 2 else " and ") + refs[-1]
            word = plural(word) if word and len(refs) > 1 else word
            new = f"{word}~{numbers}" if word else numbers
            self.note(chunk, m.start(), f"\"{m.group(0)}\"{{where}} is now \"{self.readable(new)}\", in this venue's "
                                        "words.")
            return new

        return CLEVEREF.sub(rename, chunk)

    def name_cited_subjects(self, chunk: str) -> str:
        """A sentence or clause does not start with a bare citation number: "Reference [3] shows", not "[3] shows"."""
        word = self.words["citation"][1]
        skipped = _skipped(chunk)

        def name(m: re.Match) -> str:
            before = chunk[:m.start()]
            starts = starts_sentence(before) or re.search(r";\s*\Z", before)
            if _inside(skipped, m.start()) or m.group(2) in NOT_A_VERB or not starts:
                return m.group(0)
            count = len(re.findall(CITATION_NUMBER, m.group(1))) + m.group(1).count(",")
            new = f"{plural(word) if count > 1 else word}~{m.group(1)}"
            self.note(chunk, m.start(), f"\"{self.readable(m.group(1))} {m.group(2)}\" is now "
                                        f"\"{self.readable(new)} {m.group(2)}\"{{where}}.")
            return new

        return CITATIONS_AS_SUBJECT.sub(name, chunk)

    def move_footnote_marks(self, chunk: str) -> str:
        """A footnote mark goes after a period or comma next to it: "traffic.¹", not "traffic¹."; colons,
        semicolons and dashes come after the mark."""
        skipped, pieces, last = _skipped(chunk), [], 0
        for m in FOOTNOTE.finditer(chunk):
            group = read_group(chunk, m.end())
            if m.start() < last or _inside(skipped, m.start()) or not group:
                continue
            end = group[1]
            while (more := FOOTNOTE.match(chunk, end)) and (group := read_group(chunk, more.end())):
                end = group[1]  # "cheap\footnote{a}\footnote{b}." moves the period before both marks
            mark = chunk[end:end + 1]
            if mark not in {".", ","} or chunk[end:end + 2] == ".." or chunk[m.start() - 1:m.start()] in ".,;:":
                continue
            left, _ = words_around(chunk[:m.start()], "")
            self.note(chunk, m.start(), f"A footnote mark{{where}} now follows the \"{mark}\" after "
                                        f"\"{normalize_space(left)}\", as footnote marks go after punctuation.")
            pieces += [chunk[last:m.start()], mark, chunk[m.start():end].lstrip()]
            last = end + 1
        return "".join(pieces) + chunk[last:]

    def place_captions(self, chunk: str) -> str:
        """Figure captions go below the figure; table captions where the venue puts them."""
        skipped = _skipped(chunk)

        def place(m: re.Match) -> str:
            env, inner = m.group(1), m.group(3)
            captions = list(CAPTION.finditer(inner))
            content = FLOAT_CONTENT.search(inner)
            if _inside(skipped, m.start()) or len(captions) != 1 or not content:
                return m.group(0)
            start = captions[0].start()
            short = read_group(inner, captions[0].end(), "[", "]")
            group = read_group(inner, short[1] if short else captions[0].end())
            if not group:
                return m.group(0)
            label = re.match(r"\s*\\label\{[^{}]*\}", inner[group[1]:])
            end = group[1] + (label.end() if label else 0)
            wanted = self.table_caption if env == "table" else "below"
            if (start < content.start()) == (wanted == "above"):
                return m.group(0)
            caption, rest = inner[start:end], inner[:start].rstrip(" \t") + inner[end:].lstrip(" \t").lstrip("\n")
            if wanted == "above":
                line = rest.rfind("\n", 0, FLOAT_CONTENT.search(rest).start()) + 1
                inner = rest[:line] + caption + "\n" + rest[line:]
            else:
                inner = rest.rstrip() + "\n" + caption + "\n"
            title = " ".join(normalize_space(latex_to_plain(group[0])).split()[:6])
            self.note(chunk, m.start(), f"The {env} \"{title}\"{{where}}: its caption moved {wanted} the {env}, "
                                        f"where this venue puts {env} captions.")
            return f"\\begin{{{env}{m.group(2)}}}{inner}\\end{{{env}{m.group(2)}}}"

        return FLOAT.sub(place, chunk)

    def spell_et_al(self, chunk: str) -> str:
        skipped = _skipped(chunk)

        def spell(m: re.Match) -> str:
            if _inside(skipped, m.start()):
                return m.group(0)
            new = "et~al." if "~" in m.group(0) else "et al."
            self.note(chunk, m.start(), f"\"{m.group(0).replace('~', ' ')}\"{{where}} is now \"et al.\".")
            return new

        return ET_AL.sub(spell, chunk)

    def add_leading_zeros(self, chunk: str) -> str:
        """A decimal number starts with its zero: "0.25", not ".25"."""
        skipped = _skipped(chunk) + [m.span() for m in SIZE_ARGUMENTS.finditer(chunk)]

        def zero(m: re.Match) -> str:
            if _inside(skipped, m.start()):
                return m.group(0)
            self.note(chunk, m.start(), f"\"{m.group(0)}\"{{where}} is now \"0{m.group(0)}\".")
            return "0" + m.group(0)

        return NO_LEADING_ZERO.sub(zero, chunk)

    def name_cited_authors(self, chunk: str) -> str:
        """In an author-year venue, a citation that is the subject of its sentence names the authors:
        "Lee et al. (2020) show", not "(Lee et al., 2020) show"."""
        skipped = _skipped(chunk)

        def typed(m: re.Match) -> str:
            names, year = self.names.get(m.group(3), ("", ""))
            typed_names = normalize_space(m.group(1) + (m.group(2) or "").replace("~", " "))
            if _inside(skipped, m.start()) or not names or names.split()[0] != m.group(1):
                return m.group(0)
            self.note(chunk, m.start(), f"\"{typed_names} ({names}, {year})\"{{where}} is now \"{names} ({year})\", "
                                        "as the sentence already names the authors.")
            return f"\\citet{{{m.group(3)}}}"

        def cite(m: re.Match) -> str:
            before = chunk[:m.start()]
            starts = starts_sentence(before) or re.search(r";\s*\Z", before)
            if _inside(skipped, m.start()) or m.group(3) in NOT_A_VERB or not starts:
                return m.group(0)
            cited = "; ".join(self.names.get(key.strip(), (key.strip(),))[0] for key in m.group(2).split(","))
            self.note(chunk, m.start(), f"The citation of {cited}{{where}} is the subject of its sentence, so it now "
                                        f"names the authors: \"Author (Year) {m.group(3)}\" instead of "
                                        f"\"(Author, Year) {m.group(3)}\".")
            return f"\\citet{m.group(1)}{{{m.group(2)}}}"

        return CITEP_SUBJECT.sub(cite, TYPED_AUTHORS.sub(typed, chunk))

    def readable(self, latex: str) -> str:
        """A reference as it prints: "Eq. (2)", "Fig. 1"."""
        number = lambda m: str(self.numbers.get(m.group(1), m.group(1)))

        def cited(m: re.Match) -> str:  # "[1], [3]", in the order the PDF prints them
            numbers = [str(self.numbers.get("cite " + key.strip(), key.strip())) for key in m.group(1).split(",")]
            return ", ".join(f"[{n}]" for n in sorted(numbers, key=lambda n: n.zfill(9)))

        latex = re.sub(r"\\eqref\{([^{}]*)\}", lambda m: f"({number(m)})", latex)
        latex = re.sub(r"\\cite\{([^{}]*)\}", cited, latex)
        return normalize_space(re.sub(r"\\ref\{([^{}]*)\}", number, latex).replace("~", " "))

    def where(self, chunk: str, at: int) -> str:
        headings = [m.group(1) for m in HEADING.finditer(chunk, 0, at)]
        return f" in \"{normalize_space(latex_to_plain(headings[-1]))}\"" if headings else self.place
