"""Dashboard metrics and aggregations."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_tenant
from backend.database import get_db
from backend.services import analytics_service

router = APIRouter()


@router.get("/summary")
async def get_summary(
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Total calls, avg duration, resolution rate, escalation count for today."""
    return await analytics_service.get_daily_summary(db, tenant_id)


@router.get("/top-intents")
async def get_top_intents(
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    return await analytics_service.get_top_intents(db, tenant_id)
