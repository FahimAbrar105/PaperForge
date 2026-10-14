# Sample paper

Two versions of the same short (fictional) paper, so you can try Paper Forge immediately.
The numbers in it are illustrative only.

## LaTeX version (`latex/`)
Upload all of these together:
- `latex/paper.tex`
- `latex/references.bib`
- `latex/figures/latency.png`
- `latex/figures/hitrate.png`

It is written for the plain `article` class with `natbib` and `geometry`; Paper Forge moves it onto the
IEEE conference template, converts `\citep` to `\cite`, and removes `geometry`.

## Markdown version (`markdown/`)
Upload all of these together:
- `markdown/paper.md`
- `markdown/references.bib`
- `markdown/figures/latency.png`
- `markdown/figures/hitrate.png`

## Try the repair loop
Upload `latex/paper.tex` and `latex/references.bib` **without** the figures. Paper Forge still produces a
PDF, with placeholder boxes where the figures go, and the report marks the missing figures as failed.
