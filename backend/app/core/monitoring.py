from __future__ import annotations

from typing import Sequence

import sentry_sdk
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

from app.core.config import Settings


_INITIALIZED = False


def init_sentry(settings: Settings) -> None:
    """Initialise Sentry once for the current process."""

    global _INITIALIZED
    if _INITIALIZED or not settings.sentry_dsn:
        return

    integrations: Sequence[object] = [
        FastApiIntegration(),
        CeleryIntegration(),
        SqlalchemyIntegration(),
    ]
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        integrations=integrations,
    )
    _INITIALIZED = True
