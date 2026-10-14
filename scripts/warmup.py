"""Fill Tectonic's package cache by formatting the bundled sample paper once for every venue.

run.bat / run.sh / the Dockerfile call this after installing Tectonic, so later compiles work offline. It
downloads the LaTeX packages each venue's template needs (tens of MB) into TECTONIC_CACHE_DIR.

    python scripts/warmup.py [marker-file]

The marker file lists the venues already cached; they are skipped, and each venue that compiles is added, so a
venue added later is cached on the next start. Exit code 0 means every venue compiled.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    marker = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    cached = set(marker.read_text().split()) if marker and marker.exists() else set()
    tmp = Path(tempfile.mkdtemp(prefix="pf-warmup-", dir=os.environ.get("PAPERFORGE_TMP") or None))
    os.environ["PAPERFORGE_DATA_DIR"] = str(tmp / "data")
    # The first compile downloads every LaTeX package, which can be slow on a weak connection.
    os.environ.setdefault("PAPERFORGE_COMPILE_TIMEOUT", "900")
    from app.agents.base import StepContext
    from app.agents.orchestrator import Orchestrator
    from app.agents.upload_handler import IncomingFile, new_job_id, store_uploads
    from app.config import get_settings
    from app.db import Database
    from app.models.job import JobStatus, UploadJob
    from app.services.job_store import JobStore
    from app.services.settings_store import UserSettings
    from app.services.venue_registry import VenueRegistry
    from app.services.workspace import JobWorkspace

    settings = get_settings()
    registry = VenueRegistry(settings.venue_rules_dir, settings.templates_dir)
    venues = [v.venue_id for v in registry.list() if v.available and v.venue_id not in cached]
    if not venues:
        shutil.rmtree(tmp, ignore_errors=True)
        return 0
    if not settings.tectonic_path:
        print("Tectonic not found; nothing to warm up.")
        return 1
    print(f"Preparing the LaTeX package cache for {', '.join(venues)} (once per venue, about 20-50 MB each)...")
    db = Database(settings.db_path)
    store = JobStore(db)
    sample = settings.sample_dir / "latex"
    paths = [sample / "paper.tex", sample / "references.bib", *sorted((sample / "figures").glob("*"))]
    failed = []
    try:
        for venue_id in venues:
            job_id = new_job_id()
            ws = JobWorkspace(settings.jobs_dir, job_id)
            handles = [p.open("rb") for p in paths]
            try:
                files = store_uploads(ws, [IncomingFile(p.name, "", h) for p, h in zip(paths, handles)], settings)
            finally:
                for h in handles:
                    h.close()
            store.create(UploadJob(job_id=job_id, venue_id=venue_id, files=files))
            ctx = StepContext(job_id=job_id, venue_id=venue_id, workspace=ws.create(), settings=settings,
                              emit=lambda step, msg, level: print(f"  [{level}] {step}: {msg}"))
            # Allow downloads during warm-up so every package lands in the cache.
            ctx.data["allow_network"] = True
            Orchestrator(ctx, store, registry, UserSettings()).run()
            job = store.get(job_id)
            if job is None or job.status != JobStatus.completed:
                print(f"Warm-up for {venue_id} did not produce a PDF: {job.error if job else 'unknown error'}")
                failed.append(venue_id)
                continue
            print(f"Warm-up OK for {venue_id}.")
            if marker:
                cached.add(venue_id)
                marker.write_text("\n".join(sorted(cached)) + "\n")
        return 2 if failed else 0
    finally:
        db.close()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
