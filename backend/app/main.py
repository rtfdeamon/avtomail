from __future__ import annotations

from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import api, web
from app.core.config import get_settings
from app.core.monitoring import init_sentry
from app.core.logging import configure_logging
from app.db import base  # noqa: F401 - ensures models are imported
from app.db.session import engine
from app.utils.bootstrap import ensure_default_admin
from app.workers.poller import InboxPoller, register_inbox_poller, start_poller, stop_poller


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    init_sentry(settings)
    configure_logging(settings.log_level)
    await ensure_default_admin(settings)
    poller = InboxPoller(settings)
    register_inbox_poller(app, poller)
    await start_poller(app)
    try:
        yield
    finally:
        await stop_poller(app)
        await engine.dispose()


def get_application() -> FastAPI:
    settings = get_settings()
    application = FastAPI(title=settings.project_name, lifespan=lifespan)
    static_dir = Path(__file__).resolve().parent / "web" / "static"
    if static_dir.exists():
        application.mount("/static", StaticFiles(directory=static_dir), name="static")
    application.include_router(web.router)
    application.include_router(api.api_router, prefix=settings.api_v1_prefix)
    return application


app = get_application()


@app.get("/health", tags=["health"])  # pragma: no cover - trivial
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}



