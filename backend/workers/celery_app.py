"""Celery app config. Webhook handlers enqueue tasks here to keep
webhook response time under 200ms (ADR-005 in CONTEXT.md).
"""

from celery import Celery

from backend.config import get_settings

settings = get_settings()

celery_app = Celery(
    "voiceagent",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "backend.workers.transcript_tasks",
        "backend.workers.analytics_tasks",
        "backend.workers.prospect_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=settings.celery_task_always_eager,
)
