"""Step 2 - Venue Analyst: venue_rules/<id>.json + bundled template -> venue_spec.json.

Pure Python, no AI. It verifies every template file exists, records its SHA-256
so the output can prove which template version was used, and validates the
rules against the VenueSpec model.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from app.agents.base import StepContext, StepError
from app.models.venue import VenueSpec
from app.validators.registry import CHECKS

STEP = "Venue Analyst"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def template_dir(directory: str, templates_root: Path) -> Path:
    """templates/<directory>, refusing paths that point outside templates/."""
    path = (templates_root / directory).resolve()
    if templates_root.resolve() not in path.parents:
        raise ValueError("Template directory escapes templates/")
    return path


def build_venue_spec(raw: dict, templates_root: Path, source_file: str | None = None) -> VenueSpec:
    data = json.loads(json.dumps(raw))  # deep copy
    tmpl = data.get("template", {})
    directory = template_dir(tmpl.get("directory", ""), templates_root)
    if not directory.is_dir():
        raise ValueError(f"Template directory not found: templates/{tmpl.get('directory')}")
    for required in (tmpl.get("main_template"), tmpl.get("section_template")):
        if required and not (directory / required).is_file():
            raise ValueError(f"Template file missing: templates/{tmpl.get('directory')}/{required}")
    files = []
    for entry in tmpl.get("files", []):
        rel = entry if isinstance(entry, str) else entry["path"]
        path = (directory / rel).resolve()
        if directory not in path.parents or not path.is_file():
            raise ValueError(f"Template file missing: templates/{tmpl.get('directory')}/{rel}")
        copy = True if isinstance(entry, str) else entry.get("copy_to_output", True)
        files.append({"path": rel, "sha256": _sha256(path), "copy_to_output": copy})
    tmpl["files"] = files
    data["template"] = tmpl
    data["schema_version"] = "1.0"
    data["source_rules_file"] = source_file
    data["generated_at"] = datetime.now(timezone.utc).isoformat()
    spec = VenueSpec.model_validate(data)
    unknown = [c.type for c in spec.checks if c.type not in CHECKS]
    if unknown:
        raise ValueError(f"Venue uses check types with no implementation: {unknown}")
    return spec


def choose_version(spec: VenueSpec, camera_ready: bool) -> VenueSpec:
    """A double-blind venue's anonymous submission, or its camera-ready version: authors shown and any extra
    pages the venue allows accepted papers."""
    if not spec.content_rules.anonymous_submission:
        return spec
    spec = spec.model_copy(deep=True)
    if not camera_ready:
        spec.display_name += " - anonymous submission"
        return spec
    spec.display_name += " - camera-ready"
    spec.content_rules.anonymous_submission = False
    limit = spec.layout.page_limit
    if limit.max_pages_main:
        limit.max_pages_main += limit.camera_ready_extra_pages
    if limit.max_pages_total:
        limit.max_pages_total += limit.camera_ready_extra_pages
    return spec


def run(ctx: StepContext, registry, camera_ready: bool = False) -> VenueSpec:
    ctx.log(STEP, f"Loading rules for venue '{ctx.venue_id}'")
    try:
        raw = registry.load_rules(ctx.venue_id)
        spec = build_venue_spec(raw, registry.templates_dir, source_file=f"{ctx.venue_id}.json")
    except (KeyError, ValueError, OSError) as exc:
        raise StepError(f"Venue configuration problem: {exc}") from exc
    spec = choose_version(spec, camera_ready)
    out = ctx.workspace.work.parent / "venue_spec.json"
    out.write_text(spec.model_dump_json(indent=2), encoding="utf-8")
    ctx.log(
        STEP,
        f"{spec.display_name}: {spec.layout.columns}-column, {spec.layout.paper_size}, "
        f"{len(spec.checks)} checks, template files verified ({len(spec.template.files)})",
        "success",
    )
    return spec
