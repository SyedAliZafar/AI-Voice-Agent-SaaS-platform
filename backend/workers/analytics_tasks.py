"""Periodic metric rollups — schedule via Celery beat for hourly/daily aggregation."""

from backend.workers.celery_app import celery_app


@celery_app.task(name="rollup_daily_metrics")
def rollup_daily_metrics() -> None:
    """Precompute expensive aggregations (top intents, sentiment trends)
    so the dashboard's /analytics endpoints stay fast at scale.
    """
    pass
