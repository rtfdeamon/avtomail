from __future__ import annotations

from celery import Celery

from app.core.config import get_settings
from app.core.monitoring import init_sentry

settings = get_settings()
init_sentry(settings)

celery_app = Celery(
    "avtomail",
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    broker_url=settings.celery_broker_url,
    result_backend=settings.celery_result_backend,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_time_limit=180,
    task_soft_time_limit=150,
    worker_hijack_root_logger=False,
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=settings.celery_task_eager_propagates,
    broker_connection_retry_on_startup=True,
)
