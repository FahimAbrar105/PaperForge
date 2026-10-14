"""Render structured tables as LaTeX table environments."""

from __future__ import annotations

import re
from typing import Callable

from app.models.manuscript import Table

NUMERIC = re.compile(r"^[\s$\\]*[-+]?(\d+[\d,]*)?(\.\d+)?\s*(%|\\%|x|ms|s)?[\s$]*(\\pm.*)?$")


def column_count(table: Table) -> int:
    return max([len(table.header)] + [len(r) for r in table.rows] + [1])


def column_spec(table: Table) -> str:
    spec = []
    for c in range(column_count(table)):
        cells = [r[c] for r in table.rows if c < len(r) and r[c].strip()]
        numeric = cells and all(NUMERIC.match(x) for x in cells)
        spec.append("c" if numeric or c > 0 else "l")
    return "".join(spec)


def is_wide(table: Table) -> bool:
    if table.wide_decided:
        return table.wide
    longest = max([sum(len(c) for c in r) for r in [table.header, *table.rows]] + [0])
    return table.wide or column_count(table) > 5 or longest > 70


def render_table(table: Table, convert: Callable[[str], str], caption_position: str = "above") -> str:
    if table.raw_latex:
        return table.raw_latex
    ncols = column_count(table)

    def row(cells: list[str]) -> str:
        cells = cells + [""] * (ncols - len(cells))
        return " & ".join(cells) + " \\\\"

    env = "table*" if is_wide(table) else "table"
    lines = [f"\\begin{{{env}}}[t]", "\\centering"]
    caption = [f"\\caption{{{convert(table.caption)}}}"] if table.caption else []
    caption += [f"\\label{{{table.label}}}"] if table.label else []
    if caption_position == "above":
        lines += caption
    lines.append(f"\\begin{{tabular}}{{{column_spec(table)}}}")
    lines.append("\\hline")
    if table.header and any(h.strip() for h in table.header):
        lines.append(row(["\\textbf{" + convert(h) + "}" if h.strip() else "" for h in table.header]))
        lines.append("\\hline")
    for r in table.rows:
        lines.append(row([convert(c) for c in r]))
    lines.append("\\hline")
    lines.append("\\end{tabular}")
    if caption_position == "below":
        lines += caption
    lines.append(f"\\end{{{env}}}")
    return "\n".join(lines)
