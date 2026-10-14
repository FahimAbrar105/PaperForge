"""Small text helpers shared by parsers and formatters."""

from __future__ import annotations

import re
import unicodedata

LATEX_SPECIALS = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}

# Characters that pdfTeX-era fonts in IEEEtran cannot typeset directly. Tectonic
# uses XeTeX, which handles most Unicode, but Times-like fonts used by IEEEtran
# lack many glyphs, so common ones are mapped to safe LaTeX commands.
UNICODE_TO_LATEX = {
    "\u2018": "`",
    "\u2019": "'",
    "\u201c": "``",
    "\u201d": "''",
    "\u2013": "--",
    "\u2014": "---",
    "\u2026": r"\ldots{}",
    "\u00a0": "~",
    "\u2009": r"\,",
    "\u202f": r"\,",
    "\u200b": "",
    "\ufeff": "",
    "\u00b0": r"\textdegree{}",
    "\u00b1": r"\ensuremath{\pm}",
    "\u00d7": r"\ensuremath{\times}",
    "\u00f7": r"\ensuremath{\div}",
    "\u2212": r"\ensuremath{-}",
    "\u2264": r"\ensuremath{\leq}",
    "\u2265": r"\ensuremath{\geq}",
    "\u2260": r"\ensuremath{\neq}",
    "\u2248": r"\ensuremath{\approx}",
    "\u221e": r"\ensuremath{\infty}",
    "\u2192": r"\ensuremath{\rightarrow}",
    "\u2190": r"\ensuremath{\leftarrow}",
    "\u21d2": r"\ensuremath{\Rightarrow}",
    "\u2208": r"\ensuremath{\in}",
    "\u2211": r"\ensuremath{\sum}",
    "\u221a": r"\ensuremath{\surd}",
    "\u00b5": r"\ensuremath{\mu}",
    "\u2022": r"\textbullet{}",
    "\u00a9": r"\textcopyright{}",
    "\u00ae": r"\textregistered{}",
    "\u2122": r"\texttrademark{}",
    "\u00a7": r"\S{}",
    "\u20ac": r"\texteuro{}",
    "\ufb01": "fi",
    "\ufb02": "fl",
    # Under XeTeX with T1 encoding a character's code point picks the glyph slot, and T1 differs from
    # Latin-1 below U+00C0 and at U+00D7/DF/F7/FF: unmapped, these print as a different letter
    # (for example '¹' as an accented z, 'ß' as 'SS'). Letters with no T1 slot are dropped.
    "\u00df": r"\ss{}",
    "\u00ff": r'\"{y}',
    "\u00a1": r"\textexclamdown{}",
    "\u00bf": r"\textquestiondown{}",
    "\u00a2": r"\textcent{}",
    "\u00a3": r"\pounds{}",
    "\u00a4": r"\textcurrency{}",
    "\u00a5": r"\textyen{}",
    "\u00a6": r"\textbrokenbar{}",
    "\u00a8": r"\textasciidieresis{}",
    "\u00aa": r"\textordfeminine{}",
    "\u00ba": r"\textordmasculine{}",
    "\u00ab": r"\guillemotleft{}",
    "\u00bb": r"\guillemotright{}",
    "\u00ac": r"\ensuremath{\neg}",
    "\u00ad": r"\-",
    "\u00af": r"\textasciimacron{}",
    "\u00b4": r"\textasciiacute{}",
    "\u00b6": r"\P{}",
    "\u00b7": r"\textperiodcentered{}",
    "\u00b8": r"\c{ }",
    "\u00bc": r"\textonequarter{}",
    "\u00bd": r"\textonehalf{}",
    "\u00be": r"\textthreequarters{}",
    "\u00f8": r"\o{}",
    "\u00d8": r"\O{}",
    "\u00e6": r"\ae{}",
    "\u00c6": r"\AE{}",
    "\u00f0": r"\dh{}",
    "\u00d0": r"\DH{}",
    "\u00fe": r"\th{}",
    "\u00de": r"\TH{}",
    "\u0141": r"\L{}",
    "\u0142": r"\l{}",
    "\u0152": r"\OE{}",
    "\u0153": r"\oe{}",
    "\u0110": r"\DJ{}",
    "\u0111": r"\dj{}",
    "\u0131": r"\i{}",
    "\u014a": r"\NG{}",
    "\u014b": r"\ng{}",
    "\u201a": r"\quotesinglbase{}",
    "\u201e": r"\quotedblbase{}",
    "\u2039": r"\guilsinglleft{}",
    "\u203a": r"\guilsinglright{}",
    "\u2010": "-",
    "\u2011": "-",
    "\u2012": "--",
    "\u2015": "---",
    "\u2020": r"\dag{}",
    "\u2021": r"\ddag{}",
    "\u2030": r"\textperthousand{}",
    "\u2032": r"\ensuremath{'}",
    "\u2033": r"\ensuremath{''}",
    "\u2191": r"\ensuremath{\uparrow}",
    "\u2193": r"\ensuremath{\downarrow}",
    "\u2194": r"\ensuremath{\leftrightarrow}",
    "\u21d0": r"\ensuremath{\Leftarrow}",
    "\u21d4": r"\ensuremath{\Leftrightarrow}",
    "\u2200": r"\ensuremath{\forall}",
    "\u2203": r"\ensuremath{\exists}",
    "\u2202": r"\ensuremath{\partial}",
    "\u2205": r"\ensuremath{\emptyset}",
    "\u2207": r"\ensuremath{\nabla}",
    "\u2209": r"\ensuremath{\notin}",
    "\u220f": r"\ensuremath{\prod}",
    "\u2217": r"\ensuremath{\ast}",
    "\u2218": r"\ensuremath{\circ}",
    "\u221d": r"\ensuremath{\propto}",
    "\u2225": r"\ensuremath{\parallel}",
    "\u2227": r"\ensuremath{\wedge}",
    "\u2228": r"\ensuremath{\vee}",
    "\u2229": r"\ensuremath{\cap}",
    "\u222a": r"\ensuremath{\cup}",
    "\u222b": r"\ensuremath{\int}",
    "\u223c": r"\ensuremath{\sim}",
    "\u2261": r"\ensuremath{\equiv}",
    "\u226a": r"\ensuremath{\ll}",
    "\u226b": r"\ensuremath{\gg}",
    "\u2282": r"\ensuremath{\subset}",
    "\u2283": r"\ensuremath{\supset}",
    "\u2286": r"\ensuremath{\subseteq}",
    "\u2287": r"\ensuremath{\supseteq}",
    "\u2295": r"\ensuremath{\oplus}",
    "\u2297": r"\ensuremath{\otimes}",
    "\u22c5": r"\ensuremath{\cdot}",
    "\u2713": r"\ensuremath{\checkmark}",
    "\u2714": r"\ensuremath{\checkmark}",
}
# Superscript and subscript digits (affiliation markers such as "Ann Lee¹").
for digit, (sup, sub) in enumerate(zip("\u2070\u00b9\u00b2\u00b3\u2074\u2075\u2076\u2077\u2078\u2079",
                                       "\u2080\u2081\u2082\u2083\u2084\u2085\u2086\u2087\u2088\u2089")):
    UNICODE_TO_LATEX[sup] = rf"\textsuperscript{{{digit}}}"
    UNICODE_TO_LATEX[sub] = rf"\textsubscript{{{digit}}}"

# The Greek alphabet, so Greek text never disappears silently (XeTeX's text fonts
# lack most Greek glyphs). Capitals that look like Latin letters use those letters.
GREEK_LOWER = ("alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi o pi rho varsigma "
               "sigma tau upsilon phi chi psi omega").split()
GREEK_UPPER = ("A B Gamma Delta E Z H Theta I K Lambda M N Xi O Pi P - Sigma T Upsilon Phi X Psi Omega").split()
for offset, name in enumerate(GREEK_LOWER):
    UNICODE_TO_LATEX[chr(0x03B1 + offset)] = r"\ensuremath{o}" if name == "o" else rf"\ensuremath{{\{name}}}"
for offset, name in enumerate(GREEK_UPPER):
    if name == "-":  # U+03A2 is unassigned
        continue
    command = rf"\mathrm{{{name}}}" if len(name) == 1 else rf"\{name}"
    UNICODE_TO_LATEX[chr(0x0391 + offset)] = rf"\ensuremath{{{command}}}"

_ACCENTS = {
    "\u0301": "'",
    "\u0300": "`",
    "\u0302": "^",
    "\u0308": '"',
    "\u0303": "~",
    "\u0327": "c",
    "\u030c": "v",
    "\u0304": "=",
    "\u0306": "u",
    "\u030a": "r",
    "\u030b": "H",
    "\u0328": "k",
    "\u0307": ".",
    "\u0323": "d",
}


def unicode_to_latex(text: str) -> str:
    """Replace characters that commonly break IEEE fonts with LaTeX equivalents."""
    return "".join(_char_to_latex(ch) for ch in text)


def _char_to_latex(ch: str) -> str:
    if ch in UNICODE_TO_LATEX:
        return UNICODE_TO_LATEX[ch]
    if ord(ch) < 128:
        return ch
    base, *marks = unicodedata.normalize("NFD", ch)
    if len(marks) == 1 and marks[0] in _ACCENTS and ord(base) < 128:
        return f"\\{_ACCENTS[marks[0]]}{{{base}}}"  # e.g. é -> \'{e}
    if base in UNICODE_TO_LATEX and all(unicodedata.combining(m) for m in marks):
        return UNICODE_TO_LATEX[base]  # e.g. Greek with tonos: keep the letter
    return ch


# Characters whose T1 slot holds a different glyph: they never cause a log warning, they just print wrong.
T1_MISMATCHED = {chr(c) for c in range(0xA1, 0xC0)} | {"\u00d7", "\u00df", "\u00f7", "\u00ff"}
VERBATIM_RE = re.compile(r"\\begin\{(verbatim|lstlisting|minted)\}.*?\\end\{\1\}|\\verb(.).*?\2", re.S)


def t1_safe(tex: str) -> str:
    """Map the characters T1 would print as a different glyph, leaving verbatim text alone."""
    def fix(chunk: str) -> str:
        return "".join(UNICODE_TO_LATEX.get(ch, ch) if ch in T1_MISMATCHED else ch for ch in chunk)

    out, pos = [], 0
    for m in VERBATIM_RE.finditer(tex):
        out += [fix(tex[pos : m.start()]), m.group(0)]
        pos = m.end()
    out.append(fix(tex[pos:]))
    return "".join(out)


def latex_escape(text: str) -> str:
    """Escape plain text for LaTeX, then map awkward Unicode."""
    escaped = "".join(LATEX_SPECIALS.get(ch, ch) for ch in text)
    return unicode_to_latex(escaped)


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


_HEADING_NUMBER = re.compile(r"^\s*(?:(?:\d+(?:\.\d+)*|[IVXLC]+|[A-Z])[.)]?\s+)(?=\S)")


def strip_heading_number(title: str) -> str:
    """'3.1 Method' -> 'Method', 'IV. RESULTS' -> 'RESULTS'. Keeps titles like 'A Study'."""
    m = _HEADING_NUMBER.match(title)
    if not m:
        return title.strip()
    token = m.group(0).strip()
    # A single capital letter followed by a lowercase word is an English word ("A Study").
    if re.fullmatch(r"[A-Z]", token) and not re.match(r"^\s*[A-Z][.)]", title):
        return title.strip()
    return title[m.end():].strip()


def smart_title(title: str) -> str:
    """Turn an ALL-CAPS heading into Title Case; leave mixed case alone."""
    letters = [c for c in title if c.isalpha()]
    if letters and all(c.isupper() for c in letters) and len(letters) > 3:
        small = {"a", "an", "and", "as", "at", "by", "for", "in", "of", "on", "or", "the", "to", "with", "via"}
        words = title.lower().split()
        return " ".join(w if (i and w in small) else w[:1].upper() + w[1:] for i, w in enumerate(words))
    return title


def word_count(text: str) -> int:
    """Approximate word count, ignoring LaTeX commands and math."""
    text = re.sub(r"\$[^$]*\$", " x ", text)
    text = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?", " ", text)
    text = re.sub(r"[{}]", " ", text)
    return len([w for w in re.split(r"\s+", text) if re.search(r"\w", w)])
