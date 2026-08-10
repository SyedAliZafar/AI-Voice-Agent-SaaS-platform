"""Prospect CRUD + ranking. No HTTP concerns here — routers/tasks call these.

Agent 1 (Prospector) lands here via upsert_from_places(); Agent 2 (Researcher)
lands here via mark_research_*(); the operator lands here via list_prospects()
and set_outreach_status().
"""

import math
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.models.prospect import Prospect
from backend.schemas.prospect import CompanyResearch

settings = get_settings()


def compute_priority(
    rating: float | None, review_count: int, website: str | None, phone: str | None
) -> float:
    """Transparent, weighted score — see config.py for the weights. Deliberately
    simple (no ML) so it's easy to explain and retune once real call outcomes exist.
    """
    rating_component = (rating or 0) / 5.0 * settings.priority_weight_rating
    reviews_component = math.log10(1 + max(review_count, 0)) * settings.priority_weight_reviews
    website_component = settings.priority_weight_website if website else 0.0
    phone_component = settings.priority_weight_phone if phone else 0.0
    return round(rating_component + reviews_component + website_component + phone_component, 4)


async def upsert_from_places(
    db: AsyncSession, tenant_id: uuid.UUID, places: list[dict], source_query: str
) -> list[Prospect]:
    """Insert new prospects, update identity fields (+ re-score) on ones we've already
    seen, keyed by (tenant_id, google_place_id). Never touches research/outreach state
    on an existing row — discovery shouldn't clobber work Agent 2 or the operator did.
    """
    result = []
    for place in places:
        place_id = place.get("google_place_id")
        if not place_id:
            continue

        existing = await db.execute(
            select(Prospect).where(
                Prospect.tenant_id == tenant_id, Prospect.google_place_id == place_id
            )
        )
        prospect = existing.scalar_one_or_none()
        priority = compute_priority(
            place.get("rating"),
            place.get("review_count", 0),
            place.get("website"),
            place.get("phone"),
        )

        if prospect:
            prospect.name = place.get("name") or prospect.name
            prospect.website = place.get("website") or prospect.website
            prospect.phone = place.get("phone") or prospect.phone
            prospect.address = place.get("address") or prospect.address
            prospect.category = place.get("category") or prospect.category
            prospect.rating = place.get("rating")
            prospect.review_count = place.get("review_count", 0)
            prospect.priority_score = priority
        else:
            prospect = Prospect(
                tenant_id=tenant_id,
                google_place_id=place_id,
                name=place.get("name") or "Unknown",
                website=place.get("website"),
                phone=place.get("phone"),
                address=place.get("address"),
                category=place.get("category"),
                rating=place.get("rating"),
                review_count=place.get("review_count", 0),
                source_query=source_query,
                priority_score=priority,
            )
            db.add(prospect)

        result.append(prospect)

    await db.commit()
    for prospect in result:
        await db.refresh(prospect)
    return result


async def list_prospects(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    research_status: str | None = None,
    outreach_status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Prospect]:
    query = select(Prospect).where(Prospect.tenant_id == tenant_id)
    if research_status:
        query = query.where(Prospect.research_status == research_status)
    if outreach_status:
        query = query.where(Prospect.outreach_status == outreach_status)
    query = query.order_by(Prospect.priority_score.desc()).limit(limit).offset(offset)

    result = await db.execute(query)
    return list(result.scalars().all())


async def get_prospect_unscoped(db: AsyncSession, prospect_id: uuid.UUID) -> Prospect | None:
    """Tenant-blind lookup — ONLY for trusted internal callers (Celery tasks acting on a
    prospect_id the system itself produced, and the mark_* helpers below).

    Never call this from a router: a prospect_id arriving over HTTP is attacker-controlled
    and must go through get_prospect() so ADR-001 isolation holds.
    """
    result = await db.execute(select(Prospect).where(Prospect.id == prospect_id))
    return result.scalar_one_or_none()


async def get_prospect(
    db: AsyncSession, prospect_id: uuid.UUID, tenant_id: uuid.UUID
) -> Prospect | None:
    """Fetch one prospect, scoped to its tenant (ADR-001). This is the router-facing
    lookup — another tenant's prospect reads as None so callers 404 rather than 403.
    """
    result = await db.execute(
        select(Prospect).where(Prospect.id == prospect_id, Prospect.tenant_id == tenant_id)
    )
    return result.scalar_one_or_none()


async def mark_research_running(db: AsyncSession, prospect_id: uuid.UUID) -> None:
    prospect = await get_prospect_unscoped(db, prospect_id)
    if not prospect:
        return
    prospect.research_status = "running"
    prospect.research_error = None
    await db.commit()


async def mark_research_ready(
    db: AsyncSession, prospect_id: uuid.UUID, research: CompanyResearch
) -> None:
    prospect = await get_prospect_unscoped(db, prospect_id)
    if not prospect:
        return
    prospect.research = research.model_dump()
    prospect.research_status = "ready"
    prospect.research_error = None
    await db.commit()


async def mark_research_failed(db: AsyncSession, prospect_id: uuid.UUID, error: str) -> None:
    prospect = await get_prospect_unscoped(db, prospect_id)
    if not prospect:
        return
    prospect.research_status = "failed"
    prospect.research_error = error
    await db.commit()


async def set_outreach_status(
    db: AsyncSession, prospect_id: uuid.UUID, tenant_id: uuid.UUID, status: str
) -> Prospect | None:
    prospect = await get_prospect(db, prospect_id, tenant_id)
    if not prospect:
        return None
    prospect.outreach_status = status
    await db.commit()
    await db.refresh(prospect)
    return prospect


async def set_status(
    db: AsyncSession, prospect_id: uuid.UUID, tenant_id: uuid.UUID, status: str
) -> Prospect | None:
    """Set the operator-facing campaign-outcome axis. Deliberately independent of
    set_outreach_status() — see the axes note in backend/models/prospect.py.
    """
    prospect = await get_prospect(db, prospect_id, tenant_id)
    if not prospect:
        return None
    prospect.status = status
    await db.commit()
    await db.refresh(prospect)
    return prospect


async def record_call(db: AsyncSession, prospect_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    prospect = await get_prospect(db, prospect_id, tenant_id)
    if not prospect:
        return
    prospect.call_count += 1
    prospect.last_called_at = datetime.now(UTC)
    if prospect.outreach_status == "not_reached":
        prospect.outreach_status = "reached"
    await db.commit()
