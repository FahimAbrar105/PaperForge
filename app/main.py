"""Paper Forge FastAPI application."""

from __future__ import annotations

import logging
import socket
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import Settings, get_settings
from app.db import Database
from app.routes import assistant, jobs, pages, settings as settings_routes, venues
from app.routes.deps import Services
from app.services.job_runner import JobRunner
from app.services.job_store import JobStore
from app.services.retention import RetentionSweeper
from app.services.settings_store import SettingsStore
from app.services.venue_registry import VenueRegistry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("paperforge")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.ensure_dirs()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = Database(settings.db_path)
        store = JobStore(db)
        interrupted = store.mark_interrupted()
        if interrupted:
            log.info("Marked %d interrupted job(s) as failed", interrupted)
        settings_store = SettingsStore(settings.settings_file)
        registry = VenueRegistry(settings.venue_rules_dir, settings.templates_dir)
        runner = JobRunner(settings, store, registry, settings_store)

        def retention_days() -> int:
            user = settings_store.load().retention_days
            return user if user is not None else settings.retention_days

        sweeper = RetentionSweeper(store, settings.jobs_dir, retention_days)
        sweeper.start()
        app.state.services = Services(settings=settings, store=store, registry=registry,
                                      settings_store=settings_store, runner=runner)
        if not settings.tectonic_path:
            log.warning("Tectonic not found: compilation will fail until it is installed (run.bat / Docker do this).")
        log.info("Paper Forge ready at http://localhost:%s", settings.port)
        try:
            yield
        finally:
            sweeper.stop()
            runner.shutdown()
            db.close()

    app = FastAPI(title="Paper Forge", version="1.0.0", lifespan=lifespan)
    app.include_router(pages.router)
    app.include_router(jobs.router)
    app.include_router(assistant.router)
    app.include_router(venues.router)
    app.include_router(settings_routes.router)
    app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):  # pragma: no cover - last resort
        log.exception("Unhandled error on %s", request.url.path)
        return JSONResponse({"detail": "Internal error. See the Paper Forge console for details."}, status_code=500)

    return app


app = create_app()


def _port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1" if host in {"0.0.0.0", ""} else host, port)) == 0


def main() -> None:
    import uvicorn

    s = get_settings()
    # A second start (run.bat opened twice) must not run the startup step: it would mark the first copy's
    # running jobs as interrupted, and then fail anyway because the port is taken.
    if _port_in_use(s.host, s.port):
        print(f"Port {s.port} is already in use. If Paper Forge is already running, open http://localhost:{s.port}")
        sys.exit(1)
    uvicorn.run("app.main:app", host=s.host, port=s.port, log_level="info")


if __name__ == "__main__":
    main()
