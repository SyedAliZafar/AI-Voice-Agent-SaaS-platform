"""Lead retry scheduler (ADR-011) — a Celery Beat task, not event-driven, since a
retry fires on a clock (backoff/business-hours), not in response to anything.

Sync entry point / async impl split: the task body just hands its coroutine to
async_bridge.run_sync — see that module for why a shared per-process loop is required.
"""

from datetime import UTC, datetime, timedelta

from backend.config import get_settings
from backend.database import AsyncSessionLocal
from backend.services import call_service, lead_service
from backend.services.retell_adapter import RetellAdapter
from backend.workers.async_bridge import run_sync as _run_sync
from backend.workers.celery_app import celery_app

settings = get_settings()


@celery_app.task(name="dispatch_due_leads")
def dispatch_due_leads() -> None:
    _run_sync(_dispatch_due_leads())


async def _dispatch_due_leads() -> None:
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as db:
        leads = await lead_service.due_leads(db, now)
        for lead in leads:
            if not lead_service.within_business_hours(lead, now):
                # Clock caught up outside the window (e.g. the beat process was down) —
                # push to the next valid slot without spending an attempt on it.
                await lead_service.reschedule_to_window(db, lead, now)
                continue
            await lead_service.dispatch_scheduled(db, lead)


@celery_app.task(name="sweep_stale_leads")
def sweep_stale_leads() -> None:
    _run_sync(_sweep_stale_leads())


async def _sweep_stale_leads() -> None:
    """A lead stuck "in_flight" past lead_stale_in_flight_minutes means either the
    call is still genuinely ongoing (a long call — reconciling is a no-op) or a
    call_ended webhook never arrived (ADR-007's exact scenario). Reconciling here
    reuses the platform-authoritative self-healing path rather than reinventing it;
    if reconcile brings the call to a terminal status, call_service's own hook
    (_fanout_lead_post_call) takes it from there.
    """
    cutoff = datetime.now(UTC) - timedelta(minutes=settings.lead_stale_in_flight_minutes)
    adapter = RetellAdapter()
    async with AsyncSessionLocal() as db:
        leads = await lead_service.stale_in_flight_leads(db, cutoff)
        for lead in leads:
            call = await lead_service.latest_call_for_lead(db, lead.id)
            if call is None:
                # Dispatch itself must have thrown after attempt bookkeeping but
                # before a Call row existed — extremely unlikely (place_test_call
                # commits the row before returning), but leaving the lead stuck
                # in_flight forever with nothing to reconcile is worse than retrying.
                await lead_service.advance_after_failure(
                    db, lead, "dispatch_error: no call record found"
                )
                continue
            if call.status == "in_progress":
                await call_service.reconcile_call(db, call, adapter)
