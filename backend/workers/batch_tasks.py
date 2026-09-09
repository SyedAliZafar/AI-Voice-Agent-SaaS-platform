"""Serial batch-run dialing tasks (see backend/services/batch_service.py).

Same asyncio.run(_impl()) split as every other task module here — see async_bridge for
why a fresh asyncio.run() per task would break asyncpg's connection pool.

advance_batch_run is enqueued from call_service._fanout_post_call once a batch item's
call reaches a terminal state; it does the actual dialing (an outbound HTTP call), kept
off the webhook request path per ADR-005. sweep_stalled_batches is the ADR-007-style
backstop: if a call_ended/call_analyzed webhook for the currently-dialing item never
arrives, nothing would ever re-enqueue advance_batch_run and the run would sit stuck
"running" forever with one item stuck "dialing".
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from backend.config import get_settings
from backend.database import AsyncSessionLocal
from backend.models.batch_run import BatchRun, BatchRunItem
from backend.services import batch_service, call_service
from backend.services.retell_adapter import RetellAdapter
from backend.workers.async_bridge import run_sync as _run_sync
from backend.workers.celery_app import celery_app

settings = get_settings()


@celery_app.task(name="advance_batch_run")
def advance_batch_run(run_id: str) -> None:
    _run_sync(_advance(run_id))


async def _advance(run_id: str) -> None:
    async with AsyncSessionLocal() as db:
        await batch_service.advance_run(db, uuid.UUID(run_id))


@celery_app.task(name="sweep_stalled_batches")
def sweep_stalled_batches() -> None:
    _run_sync(_sweep_stalled_batches())


async def _sweep_stalled_batches() -> None:
    """A batch item stuck "dialing" past batch_stall_minutes means its terminal webhook
    never arrived (ADR-007's exact scenario, applied to batch items instead of leads).
    reconcile_call is the authority here, never the clock directly: only advance the run
    if the platform actually confirms the call ended, so a genuinely long call never
    gets a second prospect dialed underneath it.
    """
    cutoff = datetime.now(UTC) - timedelta(minutes=settings.batch_stall_minutes)
    adapter = RetellAdapter()
    async with AsyncSessionLocal() as db:
        stalled = (
            await db.execute(
                select(BatchRunItem, BatchRun.tenant_id)
                .join(BatchRun, BatchRun.id == BatchRunItem.run_id)
                .where(
                    BatchRunItem.status == "dialing",
                    BatchRunItem.dialed_at < cutoff,
                    BatchRun.status == "running",
                )
            )
        ).all()

        for item, tenant_id in stalled:
            if not item.call_id:
                # Dialing was claimed but _dial_item never reached the point of
                # stamping a local call_id (e.g. the worker died mid-dial) — nothing to
                # reconcile, so give up on this item and push the run past it.
                run_id = await batch_service.mark_item_stalled_and_advance(db, item.id)
                if run_id:
                    advance_batch_run.delay(str(run_id))
                continue

            call = await call_service.get_call(db, item.call_id, tenant_id)
            if not call:
                continue
            await call_service.reconcile_call(db, call, adapter)
            # If that moved the call to a terminal status, it already fired
            # _fanout_post_call -> mark_item_done_and_advance -> advance_batch_run.
            # Nothing left to do here either way.
