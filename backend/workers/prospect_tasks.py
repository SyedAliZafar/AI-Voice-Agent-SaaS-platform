"""Prospecting pipeline tasks — Agent 1 (discovery) and Agent 2 (research).

Follows the asyncio.run(_impl()) pattern established in transcript_tasks.py: Celery
tasks are sync entry points, real work is async. discover_prospects auto-chains
research_prospect per newly-seen prospect so the pipeline runs unattended end to end
(the operator only ever decides who to call and when — see phase2.md).

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
from typing import Any

from backend.database import AsyncSessionLocal
from backend.schemas.prospect import CompanyResearch
from backend.services import places_service, prospect_service, research_service
from backend.workers.celery_app import celery_app


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
            db, uuid.UUID(tenant_id), places, source_query=query
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
        prospect = await prospect_service.get_prospect(db, pid)
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
