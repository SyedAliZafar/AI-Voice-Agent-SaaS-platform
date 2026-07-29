"""Metrics computation for the dashboard."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Integer, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.call import Call


async def get_daily_summary(db: AsyncSession, tenant_id: uuid.UUID) -> dict:
    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)

    result = await db.execute(
        select(
            func.count(Call.id),
            func.avg(Call.duration_sec),
            func.sum((Call.status == "resolved").cast(Integer)),
            func.sum((Call.status == "escalated").cast(Integer)),
        ).where(Call.tenant_id == tenant_id, Call.started_at >= today_start)
    )
    total, avg_duration, resolved, escalated = result.one()
    total = total or 0

    return {
        "total_calls": total,
        "avg_duration_sec": round(avg_duration or 0),
        "resolution_rate": round((resolved or 0) / total * 100, 1) if total else 0,
        "escalated_count": escalated or 0,
    }


async def get_top_intents(db: AsyncSession, tenant_id: uuid.UUID) -> list[dict]:
    """Placeholder — real implementation reads a classified `intent` column
    populated during post-call transcript processing (see transcript_tasks.py)."""
    return [
        {"intent": "check_appointment", "pct": 34},
        {"intent": "request_pricing", "pct": 28},
        {"intent": "speak_to_human", "pct": 16},
        {"intent": "cancel_reschedule", "pct": 12},
    ]
