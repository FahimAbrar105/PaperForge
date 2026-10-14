"""Per-job cache so identical AI requests are never sent twice."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


class JobAICache:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._data: dict[str, dict] = {}
        if path and path.exists():
            try:
                self._data = json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                self._data = {}

    @staticmethod
    def key(task: str, system: str, prompt: str) -> str:
        return hashlib.sha256(f"{task}\x00{system}\x00{prompt}".encode("utf-8")).hexdigest()

    def get(self, key: str) -> dict | None:
        return self._data.get(key)

    def put(self, key: str, value: dict) -> None:
        self._data[key] = value
        if self.path:
            try:
                self.path.write_text(json.dumps(self._data), encoding="utf-8")
            except OSError:
                pass
