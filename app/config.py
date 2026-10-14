"""Application configuration.

Everything is configurable through environment variables prefixed with
``PAPERFORGE_``. Defaults are chosen so the app works out of the box, both in
the portable Windows runtime and inside the Docker image.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    return Path(raw).expanduser().resolve() if raw else default


def _find_tectonic() -> str | None:
    explicit = os.environ.get("PAPERFORGE_TECTONIC")
    if explicit:
        return explicit
    for candidate in (
        PROJECT_ROOT / "runtime" / "tectonic" / "tectonic.exe",
        PROJECT_ROOT / "runtime" / "tectonic" / "tectonic",
    ):
        if candidate.is_file():
            return str(candidate)
    return shutil.which("tectonic")


@dataclass(frozen=True)
class Settings:
    project_root: Path = PROJECT_ROOT
    data_dir: Path = field(default_factory=lambda: _env_path("PAPERFORGE_DATA_DIR", PROJECT_ROOT / "output"))
    templates_dir: Path = PROJECT_ROOT / "templates"
    venue_rules_dir: Path = PROJECT_ROOT / "venue_rules"
    static_dir: Path = PROJECT_ROOT / "app" / "static"
    sample_dir: Path = PROJECT_ROOT / "sample_paper"

    host: str = field(default_factory=lambda: os.environ.get("PAPERFORGE_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _env_int("PAPERFORGE_PORT", 8000))

    max_file_mb: int = field(default_factory=lambda: _env_int("PAPERFORGE_MAX_FILE_MB", 20))
    max_total_mb: int = field(default_factory=lambda: _env_int("PAPERFORGE_MAX_TOTAL_MB", 50))
    max_files: int = field(default_factory=lambda: _env_int("PAPERFORGE_MAX_FILES", 40))
    retention_days: int = field(default_factory=lambda: _env_int("PAPERFORGE_RETENTION_DAYS", 7))
    max_repair_iterations: int = field(default_factory=lambda: _env_int("PAPERFORGE_MAX_ITERATIONS", 5))
    compile_timeout_s: int = field(default_factory=lambda: _env_int("PAPERFORGE_COMPILE_TIMEOUT", 180))
    max_ai_calls_per_job: int = field(default_factory=lambda: _env_int("PAPERFORGE_MAX_AI_CALLS", 3))
    worker_threads: int = field(default_factory=lambda: _env_int("PAPERFORGE_WORKERS", 2))

    tectonic_path: str | None = field(default_factory=_find_tectonic)

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "paperforge.db"

    @property
    def settings_file(self) -> Path:
        return self.data_dir / "settings.json"

    @property
    def max_file_bytes(self) -> int:
        return self.max_file_mb * 1024 * 1024

    @property
    def max_total_bytes(self) -> int:
        return self.max_total_mb * 1024 * 1024

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_dir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
