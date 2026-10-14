"""Word equations (Office Math Markup, OMML) to LaTeX math.

Covers what papers use: fractions, sub- and superscripts, roots, sums and integrals, brackets, functions,
limits, accents, bars, braces, matrices and equation arrays. Anything else keeps its text.
"""

from __future__ import annotations

import re
import unicodedata

from docx.oxml.ns import qn

from app.parsers.text_utils import UNICODE_TO_LATEX

MATH_SYMBOLS = {ch: m.group(1) for ch, tex in UNICODE_TO_LATEX.items()
                if (m := re.fullmatch(r"\\ensuremath\{(.+)\}", tex))}
MATH_SYMBOLS.update({
    "\u2212": "-", "\u00b7": r"\cdot", "\u2026": r"\ldots", "\u22ef": r"\cdots", "\u2032": "'",
    "\u2223": "|", "\u2016": r"\|", "\u27e8": r"\langle", "\u27e9": r"\rangle",
    "\u211d": r"\mathbb{R}", "\u2115": r"\mathbb{N}", "\u2124": r"\mathbb{Z}", "\u211a": r"\mathbb{Q}",
    "\u2102": r"\mathbb{C}", "\u21a6": r"\mapsto", "\u22a5": r"\perp", "\u2216": r"\setminus",
    "\u00b0": r"^{\circ}", "\u2061": "", "\u2062": "", "\u2063": "", "\u200b": "",
    "{": r"\{", "}": r"\}", "%": r"\%", "#": r"\#", "&": r"\&", "_": r"\_", "$": r"\$", "~": r"\sim",
    "\\": r"\backslash",
})
BIG_OPERATORS = {"\u2211": r"\sum", "\u220f": r"\prod", "\u2210": r"\coprod", "\u222b": r"\int", "\u222c": r"\iint",
                 "\u222d": r"\iiint", "\u222e": r"\oint", "\u22c3": r"\bigcup", "\u22c2": r"\bigcap",
                 "\u22c1": r"\bigvee", "\u22c0": r"\bigwedge", "\u2a01": r"\bigoplus", "\u2a02": r"\bigotimes"}
ACCENTS = {"\u0302": r"\hat", "\u0303": r"\tilde", "\u0304": r"\bar", "\u0305": r"\overline", "\u0307": r"\dot",
           "\u0308": r"\ddot", "\u20d7": r"\vec", "\u030c": r"\check", "\u0306": r"\breve", "\u0301": r"\acute",
           "\u0300": r"\grave"}
FUNCTIONS = {"sin", "cos", "tan", "cot", "sec", "csc", "arcsin", "arccos", "arctan", "sinh", "cosh", "tanh",
             "log", "ln", "lg", "exp", "lim", "max", "min", "sup", "inf", "det", "dim", "ker", "deg", "gcd",
             "arg", "Pr", "liminf", "limsup", "argmax", "argmin"}
OPERATORS = {"Var", "Cov", "Corr", "Tr", "tr", "rank", "diag", "sgn", "sign", "softmax", "erf"}
DELIMITERS = {"(": "(", ")": ")", "[": "[", "]": "]", "{": r"\{", "}": r"\}", "|": "|", "\u2016": r"\|",
              "\u27e8": r"\langle", "\u27e9": r"\rangle", "\u2308": r"\lceil", "\u2309": r"\rceil",
              "\u230a": r"\lfloor", "\u230b": r"\rfloor", "": "."}


def omml_to_latex(element) -> str:
    """LaTeX for an m:oMath or m:oMathPara element (without the surrounding $ or equation environment)."""
    return re.sub(r"\s+", " ", _children(element)).strip()


def _children(el) -> str:
    """Word often splits an upright word such as "Var" into one run per letter; those runs are joined first."""
    out, word = [], ""
    for child in el:
        letters = _upright_letters(child)
        if letters is not None:
            word += letters
            continue
        if word:
            out.append(_upright(word))
            word = ""
        out.append(_node(child))
    return "".join(out) + (_upright(word) if word else "")


def _upright_letters(el) -> str | None:
    if el.tag != qn("m:r"):
        return None
    text = "".join(t.text or "" for t in el.iter(qn("m:t")))
    plain = _prop(el, "m:rPr", "m:sty") == "p" or _prop(el, "m:rPr", "m:nor") in {"1", "on", "true"}
    return text if plain and re.fullmatch(r"[A-Za-z][A-Za-z ]*", text) else None


def _upright(word: str) -> str:
    if word in FUNCTIONS or word in OPERATORS:
        return _function_name(word) + " "
    return r"\mathrm{" + word + "}"


def _part(el, name: str) -> str:
    child = el.find(qn(name))
    return _children(child) if child is not None else ""


def _prop(el, prop: str, name: str, default: str | None = None) -> str | None:
    """The m:val of a property such as m:fPr/m:type."""
    pr = el.find(qn(prop))
    node = pr.find(qn(name)) if pr is not None else None
    return node.get(qn("m:val"), default) if node is not None else default


def _group(tex: str) -> str:
    return tex if len(tex) == 1 else "{" + tex + "}"


def _text(run) -> str:
    text = "".join(t.text or "" for t in run.iter(qn("m:t")))
    if _upright_letters(run) is not None:
        return _upright(text)
    out = []
    for ch in text:
        tex = BIG_OPERATORS.get(ch) or MATH_SYMBOLS.get(ch)
        if tex is None:
            out.append(unicodedata.normalize("NFKC", ch))  # math italic letters such as U+1D465 become x
        else:
            out.append(tex + " " if re.search(r"\\[A-Za-z]+$", tex) else tex)  # "\alpha x", not "\alphax"
    return "".join(out)


def _node(el) -> str:
    tag = el.tag.split("}")[-1]
    if tag.endswith("Pr") or tag in {"t"}:
        return ""
    handler = HANDLERS.get(tag)
    return handler(el) if handler else _children(el)


def _fraction(el) -> str:
    num, den = _part(el, "m:num"), _part(el, "m:den")
    kind = _prop(el, "m:fPr", "m:type", "bar")
    if kind == "lin":
        return f"{_group(num)}/{_group(den)}"
    if kind == "noBar":
        return rf"\genfrac{{}}{{}}{{0pt}}{{}}{{{num}}}{{{den}}}"
    return rf"\frac{{{num}}}{{{den}}}"


def _script(el) -> str:
    base, sub, sup = _part(el, "m:e"), _part(el, "m:sub"), _part(el, "m:sup")
    out = _group(base) if base else "{}"
    out += f"_{{{sub}}}" if sub else ""
    out += f"^{{{sup}}}" if sup else ""
    return out


def _prescript(el) -> str:
    return f"{{}}_{{{_part(el, 'm:sub')}}}^{{{_part(el, 'm:sup')}}}{_group(_part(el, 'm:e'))}"


def _radical(el) -> str:
    degree = _part(el, "m:deg")
    hidden = _prop(el, "m:radPr", "m:degHide") in {"1", "on", "true"}
    return (rf"\sqrt[{degree}]" if degree and not hidden else r"\sqrt") + "{" + _part(el, "m:e") + "}"


def _nary(el) -> str:
    op = BIG_OPERATORS.get(_prop(el, "m:naryPr", "m:chr", "\u222b"), r"\int")
    sub, sup = _part(el, "m:sub"), _part(el, "m:sup")
    out = op + (f"_{{{sub}}}" if sub else "") + (f"^{{{sup}}}" if sup else "")
    return out + " " + _part(el, "m:e")


def _delimiter(el) -> str:
    begin = _prop(el, "m:dPr", "m:begChr", "(")
    end = _prop(el, "m:dPr", "m:endChr", ")")
    separator = _prop(el, "m:dPr", "m:sepChr", "|")
    inner = (DELIMITERS.get(separator, separator) + " ").join(_children(e) for e in el.findall(qn("m:e")))
    return rf"\left{DELIMITERS.get(begin, begin)} {inner} \right{DELIMITERS.get(end, end)}"


def _function_name(word: str) -> str:
    return "\\" + word if word in FUNCTIONS and word not in {"argmax", "argmin"} else rf"\operatorname{{{word}}}"


def _function(el) -> str:
    name = _part(el, "m:fName").strip()
    arg = _part(el, "m:e")
    if name in FUNCTIONS or re.fullmatch(r"\\mathrm\{(\w+)\}", name):
        name = _function_name(re.sub(r"\\mathrm\{(\w+)\}", r"\1", name))
    return f"{name}{{{arg}}}" if not name.endswith("}") else f"{name} {arg}"


def _lower_limit(el) -> str:
    base, limit = _part(el, "m:e").strip(), _part(el, "m:lim")
    if base.removeprefix("\\") in FUNCTIONS:
        return _function_name(base.removeprefix("\\")) + f"_{{{limit}}}"
    return rf"\underset{{{limit}}}{{{base}}}"


def _upper_limit(el) -> str:
    return rf"\overset{{{_part(el, 'm:lim')}}}{{{_part(el, 'm:e')}}}"


def _accent(el) -> str:
    command = ACCENTS.get(_prop(el, "m:accPr", "m:chr", "\u0302"), r"\hat")
    return f"{command}{{{_part(el, 'm:e')}}}"


def _bar(el) -> str:
    command = r"\overline" if _prop(el, "m:barPr", "m:pos", "bot") == "top" else r"\underline"
    return f"{command}{{{_part(el, 'm:e')}}}"


def _group_char(el) -> str:
    top = _prop(el, "m:groupChrPr", "m:pos", "bot") == "top"
    return (r"\overbrace" if top else r"\underbrace") + "{" + _part(el, "m:e") + "}"


def _matrix(el) -> str:
    rows = [" & ".join(_children(e) for e in row.findall(qn("m:e"))) for row in el.findall(qn("m:mr"))]
    return r"\begin{matrix} " + r" \\ ".join(rows) + r" \end{matrix}"


def _equation_array(el) -> str:
    rows = [_children(e) for e in el.findall(qn("m:e"))]
    return r"\begin{aligned} " + r" \\ ".join(rows) + r" \end{aligned}"


HANDLERS = {
    "r": _text, "f": _fraction, "sSup": _script, "sSub": _script, "sSubSup": _script, "sPre": _prescript,
    "rad": _radical, "nary": _nary, "d": _delimiter, "func": _function, "limLow": _lower_limit,
    "limUpp": _upper_limit, "acc": _accent, "bar": _bar, "groupChr": _group_char, "m": _matrix,
    "eqArr": _equation_array, "borderBox": lambda el: r"\boxed{" + _part(el, "m:e") + "}",
}
