from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import api
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db import base  # noqa: F401 - ensures models are imported
from app.db.session import engine


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    yield
    await engine.dispose()


def get_application() -> FastAPI:
    settings = get_settings()
    application = FastAPI(title=settings.project_name, lifespan=lifespan)
    application.include_router(api.api_router, prefix=settings.api_v1_prefix)
    return application


app = get_application()


@app.get("/health", tags=["health"])  # pragma: no cover - trivial
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}
