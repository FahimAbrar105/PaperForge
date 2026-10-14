"""Per-job workspaces, safe path handling and packaging."""

from __future__ import annotations

import re
import shutil
import unicodedata
import zipfile
from pathlib import Path

_SAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


class UnsafePathError(ValueError):
    pass


def sanitize_filename(name: str, default: str = "file") -> str:
    """Return a safe basename: no directories, no control characters, ASCII only."""
    name = name.replace("\\", "/").split("/")[-1]
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    name = _SAFE_CHARS.sub("_", name).strip("._ ")
    if not name:
        name = default
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    if stem.lower() in _RESERVED:
        stem = f"_{stem}"
    stem = stem[:100] or default
    ext = ext[:10]
    return f"{stem}.{ext}" if ext else stem


def safe_join(base: Path, *parts: str) -> Path:
    """Join paths and refuse anything that escapes ``base``."""
    base_resolved = base.resolve()
    candidate = base_resolved.joinpath(*parts).resolve()
    if candidate != base_resolved and base_resolved not in candidate.parents:
        raise UnsafePathError(f"Path escapes workspace: {'/'.join(parts)}")
    return candidate


class JobWorkspace:
    """Directory layout for one job: uploads/, work/, final/, logs/."""

    def __init__(self, jobs_dir: Path, job_id: str) -> None:
        if not re.fullmatch(r"[a-f0-9]{8,32}", job_id):
            raise UnsafePathError("Invalid job id")
        self.root = safe_join(jobs_dir, job_id)
        self.uploads = self.root / "uploads"
        self.work = self.root / "work"
        self.final = self.root / "final"
        self.logs = self.root / "logs"

    def create(self) -> "JobWorkspace":
        for d in (self.uploads, self.work, self.final, self.logs):
            d.mkdir(parents=True, exist_ok=True)
        return self

    def unique_upload_path(self, filename: str) -> Path:
        name = sanitize_filename(filename)
        target = safe_join(self.uploads, name)
        counter = 1
        while target.exists():
            stem, dot, ext = name.rpartition(".")
            if not dot:
                stem, ext = name, ""
            candidate = f"{stem}_{counter}.{ext}" if ext else f"{stem}_{counter}"
            target = safe_join(self.uploads, candidate)
            counter += 1
        return target

    def delete(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


BUILD_ARTIFACT_SUFFIXES = {".aux", ".log", ".out", ".bbl", ".blg", ".toc", ".synctex.gz", ".fls", ".fdb_latexmk"}


def zip_latex_project(src_dir: Path, zip_path: Path) -> Path:
    """Package the LaTeX source tree (without build artifacts) into a ZIP archive."""
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(src_dir.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(src_dir)
            if rel.parts and rel.parts[0] == "build":
                continue
            if any(str(path).endswith(s) for s in BUILD_ARTIFACT_SUFFIXES):
                continue
            zf.write(path, arcname=str(Path("paper") / rel).replace("\\", "/"))
    return zip_path
