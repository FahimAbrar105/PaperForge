"""Make a ZIP of Paper Forge to share: the app without your runtime, settings, API key or jobs.

    python scripts/make_zip.py [zip-path]

Writes paper-forge.zip next to this folder unless a path is given. The person who unzips it starts run.bat (or
run.sh), which downloads its own Python and Tectonic.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEFT_OUT = {"runtime", "output", ".git", ".claude", "__pycache__", ".pytest_cache", ".venv", "venv"}


def shared_files() -> list[Path]:
    files = [p for p in ROOT.rglob("*") if p.is_file() and not LEFT_OUT & set(p.relative_to(ROOT).parts)
             and p.suffix != ".pyc"]
    keep = ROOT / "output" / ".gitkeep"  # so the empty output folder comes along
    return sorted(files + [keep] if keep.exists() else files)


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "paper-forge.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in shared_files():
            zf.write(path, Path("paper-forge") / path.relative_to(ROOT))
    print(f"Wrote {target} ({target.stat().st_size / 1e6:.1f} MB). Your settings, API key and jobs are not in it.")


if __name__ == "__main__":
    main()
