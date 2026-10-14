"""Discover venues from venue_rules/*.json.

Adding a venue means adding ``venue_rules/<venue_id>.json`` and
``templates/<venue_id>/``. No Python changes are needed unless a brand-new
check type is introduced.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ValidationError


class VenueSummary(BaseModel):
    venue_id: str
    display_name: str
    venue_type: str
    available: bool
    anonymous_submission: bool = False
    problem: str | None = None


class VenueRegistry:
    def __init__(self, rules_dir: Path, templates_dir: Path) -> None:
        self.rules_dir = rules_dir
        self.templates_dir = templates_dir

    def rule_files(self) -> list[Path]:
        return sorted(self.rules_dir.glob("*.json"))

    def load_rules(self, venue_id: str) -> dict:
        path = self.rules_dir / f"{venue_id}.json"
        if not path.is_file() or path.parent.resolve() != self.rules_dir.resolve():
            raise KeyError(f"Unknown venue: {venue_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def list(self) -> list[VenueSummary]:
        from app.agents.venue_analyst import build_venue_spec  # local import avoids a cycle

        out: list[VenueSummary] = []
        for path in self.rule_files():
            venue_id = path.stem
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                spec = build_venue_spec(raw, self.templates_dir, source_file=path.name)
                out.append(VenueSummary(venue_id=spec.venue_id, display_name=spec.display_name,
                                        venue_type=spec.venue_type, available=True,
                                        anonymous_submission=spec.content_rules.anonymous_submission))
            except (OSError, ValueError, ValidationError, KeyError) as exc:
                out.append(VenueSummary(venue_id=venue_id, display_name=venue_id, venue_type="unknown",
                                        available=False, problem=str(exc)[:300]))
        return out

    def exists(self, venue_id: str) -> bool:
        return any(v.venue_id == venue_id and v.available for v in self.list())
