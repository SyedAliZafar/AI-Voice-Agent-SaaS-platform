"""Tests for the lead-scheduler Celery task bodies (ADR-011) — exercised as plain
async functions against the test session, same _session_factory substitution pattern
test_prospects.py uses for prospect_tasks.
"""

from datetime import UTC, datetime, timedelta

import pytest

from backend.schemas.agent import AgentCreate
from backend.services import agent_service, call_service, lead_service
from backend.workers import lead_tasks


def _session_factory(session):
    class _Factory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return session

        async def __aexit__(self, *exc_info):
            return False

    return _Factory()


async def _agent(db_session, tenant_id):
    return await agent_service.create_agent(
        db_session,
        tenant_id,
        AgentCreate(name="SDR", system_prompt="Hi.", platform="retell"),
    )


@pytest.fixture
def placed_calls(monkeypatch) -> list[dict]:
    from backend.services import test_call_service

    calls: list[dict] = []

    async def fake_place_test_call(
        db, agent_id, tenant_id, to_number, system_prompt_override=None, lead_id=None
    ):
        calls.append({"to_number": to_number, "lead_id": lead_id})
        return {"call_id": f"mock_call_{len(calls)}", "from_number": "+1", "status": "dialing"}

    monkeypatch.setattr(test_call_service, "place_test_call", fake_place_test_call)
    return calls


@pytest.mark.asyncio
async def test_dispatch_due_leads_dials_a_due_lead(
    db_session, tenant_id, monkeypatch, placed_calls
):
    agent = await _agent(db_session, tenant_id)
    lead = await lead_service.create_lead(
        db_session,
        tenant_id,
        {"phone": "+491701111111", "agent_id": agent.id, "timezone": "UTC"},
    )
    lead.retry_state = "scheduled"

    # Fixed, always-business-hours instant (Thursday, noon UTC) rather than the real wall
    # clock: _dispatch_due_leads computes `now = datetime.now(UTC)` itself and this test's
    # UTC-timezoned lead has no other way to stay inside within_business_hours' 9-18
    # window — this test previously failed whenever it happened to run outside that
    # window (e.g. ~20:00 UTC), which had nothing to do with the dispatch logic under
    # test.
    frozen_now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen_now if tz else frozen_now.replace(tzinfo=None)

    lead.next_attempt_at = frozen_now - timedelta(minutes=1)
    await db_session.commit()

    monkeypatch.setattr(lead_tasks, "AsyncSessionLocal", _session_factory(db_session))
    monkeypatch.setattr(lead_tasks, "datetime", _FrozenDatetime)
    await lead_tasks._dispatch_due_leads()

    assert len(placed_calls) == 1
    refreshed = await lead_service.get_lead(db_session, lead.id, tenant_id)
    assert refreshed.retry_state == "in_flight"


@pytest.mark.asyncio
async def test_dispatch_due_leads_leaves_non_scheduled_leads_alone(
    db_session, tenant_id, monkeypatch, placed_calls
):
    agent = await _agent(db_session, tenant_id)
    lead = await lead_service.create_lead(
        db_session, tenant_id, {"phone": "+491701111111", "agent_id": agent.id}
    )  # stays "paused" — never started

    monkeypatch.setattr(lead_tasks, "AsyncSessionLocal", _session_factory(db_session))
    await lead_tasks._dispatch_due_leads()

    assert placed_calls == []
    refreshed = await lead_service.get_lead(db_session, lead.id, tenant_id)
    assert refreshed.retry_state == "paused"


@pytest.mark.asyncio
async def test_dispatch_due_leads_defers_a_due_lead_outside_business_hours(
    db_session, tenant_id, monkeypatch, placed_calls
):
    """A tick that runs after downtime can find a lead whose slot has already passed
    into a non-business hour — it must reschedule, not dial at 2am, and must not spend
    an attempt doing so."""
    agent = await _agent(db_session, tenant_id)
    lead = await lead_service.create_lead(
        db_session,
        tenant_id,
        {"phone": "+491701111111", "agent_id": agent.id, "timezone": "UTC"},
    )
    lead.retry_state = "scheduled"
    # Due in the past, at a UTC hour guaranteed outside 09:00-18:00.
    stale_slot = datetime.now(UTC).replace(hour=2, minute=0, second=0, microsecond=0)
    lead.next_attempt_at = stale_slot - timedelta(days=1)
    await db_session.commit()

    monkeypatch.setattr(lead_tasks, "AsyncSessionLocal", _session_factory(db_session))
    monkeypatch.setattr(
        lead_tasks,
        "datetime",
        type("_FixedDatetime", (), {"now": staticmethod(lambda tz=None: stale_slot)}),
    )
    await lead_tasks._dispatch_due_leads()

    assert placed_calls == []
    refreshed = await lead_service.get_lead(db_session, lead.id, tenant_id)
    assert refreshed.retry_state == "scheduled"
    assert refreshed.attempt_count == 0
    assert refreshed.next_attempt_at.hour == 9


class _StubAdapter:
    def __init__(self, payload: dict):
        self.payload = payload

    async def get_call(self, call_external_id: str) -> dict:
        return self.payload


@pytest.mark.asyncio
async def test_sweep_reconciles_a_stale_in_flight_lead(
    db_session, tenant_id, monkeypatch, placed_calls
):
    agent = await _agent(db_session, tenant_id)
    lead = await lead_service.create_lead(
        db_session,
        tenant_id,
        {"phone": "+491701111111", "agent_id": agent.id, "timezone": "UTC"},
    )
    lead.retry_state = "in_flight"
    lead.attempt_count = 1
    lead.last_attempt_at = datetime.now(UTC) - timedelta(minutes=30)
    await db_session.commit()

    await call_service.create_outbound_call_record(
        db_session, tenant_id, agent.id, "ext_stale_1", lead.phone, lead_id=lead.id
    )

    monkeypatch.setattr(lead_tasks, "AsyncSessionLocal", _session_factory(db_session))
    monkeypatch.setattr(
        lead_tasks,
        "RetellAdapter",
        lambda: _StubAdapter(
            {"call_status": "ended", "disconnection_reason": "dial_no_answer", "duration_ms": 1000}
        ),
    )
    await lead_tasks._sweep_stale_leads()

    refreshed_call = await call_service.get_call_by_external_id(db_session, "ext_stale_1")
    assert refreshed_call.status == "failed"
    refreshed_lead = await lead_service.get_lead(db_session, lead.id, tenant_id)
    assert refreshed_lead.retry_state == "scheduled"
    # The attempt was already counted when the call was originally dispatched —
    # evaluating its (now-known) outcome must not count it a second time.
    assert refreshed_lead.attempt_count == 1


@pytest.mark.asyncio
async def test_sweep_leaves_a_genuinely_ongoing_call_alone(
    db_session, tenant_id, monkeypatch, placed_calls
):
    agent = await _agent(db_session, tenant_id)
    lead = await lead_service.create_lead(
        db_session,
        tenant_id,
        {"phone": "+491701111111", "agent_id": agent.id, "timezone": "UTC"},
    )
    lead.retry_state = "in_flight"
    lead.last_attempt_at = datetime.now(UTC) - timedelta(minutes=30)
    await db_session.commit()

    await call_service.create_outbound_call_record(
        db_session, tenant_id, agent.id, "ext_ongoing_1", lead.phone, lead_id=lead.id
    )

    monkeypatch.setattr(lead_tasks, "AsyncSessionLocal", _session_factory(db_session))
    monkeypatch.setattr(
        lead_tasks, "RetellAdapter", lambda: _StubAdapter({"call_status": "ongoing"})
    )
    await lead_tasks._sweep_stale_leads()

    refreshed_lead = await lead_service.get_lead(db_session, lead.id, tenant_id)
    assert refreshed_lead.retry_state == "in_flight"  # untouched — really still going
