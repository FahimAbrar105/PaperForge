from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class RepairAction(BaseModel):
    iteration: int
    issue_kind: str
    action: str
    file: str | None = None
    source: Literal["deterministic", "gemini", "ollama"] = "deterministic"
