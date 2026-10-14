"""Jinja2 environment with LaTeX-friendly delimiters (\\VAR{...}, \\BLOCK{...})."""

from __future__ import annotations

from pathlib import Path

import jinja2


def make_env(template_dir: Path) -> jinja2.Environment:
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(template_dir)),
        block_start_string=r"\BLOCK{",
        block_end_string="}",
        variable_start_string=r"\VAR{",
        variable_end_string="}",
        comment_start_string=r"\#{",
        comment_end_string="}",
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=False,
        keep_trailing_newline=True,
        undefined=jinja2.StrictUndefined,
    )


def render(template_dir: Path, template_name: str, context: dict) -> str:
    return make_env(template_dir).get_template(template_name).render(**context)
