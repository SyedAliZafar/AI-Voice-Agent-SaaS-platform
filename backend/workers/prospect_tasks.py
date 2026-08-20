"""Prospecting pipeline tasks — Agent 1 (discovery) and Agent 2 (research).

Follows the asyncio.run(_impl()) pattern established in transcript_tasks.py: Celery
tasks are sync entry points, real work is async. discover_prospects auto-chains
research_prospect per newly-seen prospect so the pipeline runs unattended end to end
(the operator only ever decides who to call and when — see phase2.md). import_from_csv
does the same per imported row (backend/api/prospects.py).

sweep_stale_prospects is the backstop for when that chain fires into nothing: a
research_prospect.delay() call only enqueues a message onto Redis — if no worker is
running to consume it (or one crashed mid-task), the message is gone the moment Redis
itself restarts (the default non-persistent dev setup), and the row is stuck "pending"
forever with no code path left that will ever touch it again. Diagnosed 2026-08-21: 14
real prospects (CSV imports from 2026-08-12 through 2026-08-19) stuck exactly this way —
Redis reachable, its queue empty, so the enqueued tasks were lost rather than waiting.
Mirrors lead_tasks.sweep_stale_leads (ADR-011), same shape: a Celery Beat tick re-drives
anything a chain should have already caught.

Note on _run_sync: with CELERY_TASK_ALWAYS_EAGER=true (the solo-dev mode from RUN.md),
.delay() executes the task body immediately, in-process. If that call originates from an
async FastAPI route (api/prospects.py does exactly this), we're already inside a running
event loop, and plain asyncio.run() would raise "cannot be called from a running event
loop". _run_sync runs the coroutine on a dedicated thread with its own loop when that
happens, and falls back to a plain asyncio.run() in a real worker process (no loop
running there). This is a real hazard, not a hypothetical — flagged because the identical
asyncio.run(_process(...)) pattern in transcript_tasks.py has the same latent issue.
"""

import asyncio
import uuid
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

from backend.config import get_settings
from backend.database import AsyncSessionLocal
from backend.schemas.prospect import CompanyResearch
from backend.services import places_service, prospect_service, research_service
from backend.workers.celery_app import celery_app

settings = get_settings()


def _run_sync(coro: Coroutine[Any, Any, None]) -> None:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(coro)
        return
    # A loop is already running on this thread (eager-mode call from an async route) —
    # run the coroutine to completion on a separate thread instead.
    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(asyncio.run, coro).result()


@celery_app.task(name="discover_prospects")
def discover_prospects(
    tenant_id: str, query: str, location: str | None, radius_m: int, limit: int
) -> None:
    _run_sync(_discover(tenant_id, query, location, radius_m, limit))


async def _discover(
    tenant_id: str, query: str, location: str | None, radius_m: int, limit: int
) -> None:
    places = await places_service.search_places(query, location, radius_m, limit)

    async with AsyncSessionLocal() as db:
        prospects = await prospect_service.upsert_from_places(
            db, uuid.UUID(tenant_id), places, source_query=query, source_location=location
        )
        # Only kick off research for rows that don't have it yet — re-running a
        # discovery query shouldn't re-research prospects we already know.
        to_research = [p for p in prospects if p.research_status == "pending"]

    for prospect in to_research:
        research_prospect.delay(str(prospect.id))


@celery_app.task(name="research_prospect")
def research_prospect(prospect_id: str) -> None:
    _run_sync(_research(prospect_id))


async def _research(prospect_id: str) -> None:
    pid = uuid.UUID(prospect_id)

    async with AsyncSessionLocal() as db:
        # Unscoped is correct here: this task is driven by a prospect_id the discovery
        # pipeline produced, not by an HTTP caller, so there's no tenant to scope to.
        prospect = await prospect_service.get_prospect_unscoped(db, pid)
        if not prospect:
            return
        name, website, address = prospect.name, prospect.website, prospect.address
        await prospect_service.mark_research_running(db, pid)

    try:
        research: CompanyResearch = await research_service.research_company(name, website, address)
    except Exception as exc:  # noqa: BLE001 — one bad prospect must not kill the pipeline
        async with AsyncSessionLocal() as db:
            await prospect_service.mark_research_failed(db, pid, str(exc))
        return

    async with AsyncSessionLocal() as db:
        await prospect_service.mark_research_ready(db, pid, research)


@celery_app.task(name="sweep_stale_prospects")
def sweep_stale_prospects() -> None:
    _run_sync(_sweep_stale_prospects())


async def _sweep_stale_prospects() -> None:
    """Re-enqueue research for any prospect stuck "pending"/"running" past
    prospect_stale_research_minutes — see module docstring for the real incident this
    covers. Simply re-dispatching is correct for both stuck states: "pending" means
    research never started at all, and "running" means mark_research_running() was the
    last thing that happened to the row — _research() only reads name/website/address
    off the prospect and re-derives everything else, so running it again from scratch
    is exactly as safe as the first attempt, just later.
    """
    cutoff = datetime.now(UTC) - timedelta(minutes=settings.prospect_stale_research_minutes)
    async with AsyncSessionLocal() as db:
        stale = await prospect_service.stale_research_prospects(db, cutoff)

    for prospect in stale:
        research_prospect.delay(str(prospect.id))
