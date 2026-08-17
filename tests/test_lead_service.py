"""Tests for lead_service — CRUD, the retry-scheduler state machine, backoff/business-
hours math, and outcome evaluation (ADR-011).
"""

from datetime import UTC, datetime, timedelta

import pytest

from backend.schemas.agent import AgentCreate
from backend.services import agent_service, call_service, lead_service


async def _agent(db_session, tenant_id):
    return await agent_service.create_agent(
        db_session,
        tenant_id,
        AgentCreate(name="SDR", system_prompt="[ROLE] You are Alex.", platform="retell"),
    )


async def _lead(db_session, tenant_id, **overrides):
    data = {
        "phone": "+491701111111",
        "business_name": "Acme HVAC",
        "source": "bark",
        "details": {},
    }
    data.update(overrides)
    return await lead_service.create_lead(db_session, tenant_id, data)


@pytest.mark.asyncio
async def test_new_lead_defaults_to_paused(db_session, tenant_id):
    lead = await _lead(db_session, tenant_id)
    assert lead.retry_state == "paused"
    assert lead.next_attempt_at is None
    assert lead.attempt_count == 0


@pytest.mark.asyncio
async def test_get_lead_is_tenant_scoped(db_session, tenant_id, other_tenant_id):
    lead = await _lead(db_session, tenant_id)
    assert await lead_service.get_lead(db_session, lead.id, other_tenant_id) is None
    assert await lead_service.get_lead(db_session, lead.id, tenant_id) is not None


@pytest.mark.asyncio
async def test_start_arms_scheduler_within_business_hours(db_session, tenant_id):
    lead = await _lead(db_session, tenant_id, timezone="Europe/London")
    started = await lead_service.start_lead(db_session, lead.id, tenant_id)

    assert started.retry_state == "scheduled"
    assert started.next_attempt_at is not None
    assert lead_service.within_business_hours(started, started.next_attempt_at)


@pytest.mark.asyncio
async def test_pause_clears_the_schedule(db_session, tenant_id):
    lead = await _lead(db_session, tenant_id)
    await lead_service.start_lead(db_session, lead.id, tenant_id)

    paused = await lead_service.pause_lead(db_session, lead.id, tenant_id)
    assert paused.retry_state == "paused"
    assert paused.next_attempt_at is None


@pytest.mark.asyncio
async def test_do_not_call_is_terminal_and_clears_schedule(db_session, tenant_id):
    lead = await _lead(db_session, tenant_id)
    await lead_service.start_lead(db_session, lead.id, tenant_id)

    dnc = await lead_service.mark_do_not_call(db_session, lead.id, tenant_id)
    assert dnc.retry_state == "do_not_call"
    assert dnc.next_attempt_at is None


class TestSnapToWindow:
    def test_leaves_a_time_already_inside_the_window_unchanged(self):
        # Wednesday 10:00 London time — squarely inside 09:00-18:00.
        dt = datetime(2026, 8, 19, 10, 0, tzinfo=UTC)
        assert lead_service._snap_to_window(dt) == dt

    def test_pushes_early_morning_to_business_start(self):
        dt = datetime(2026, 8, 19, 3, 0, tzinfo=UTC)  # Wednesday 03:00
        snapped = lead_service._snap_to_window(dt)
        assert snapped.hour == 9
        assert snapped.date() == dt.date()

    def test_pushes_after_hours_to_next_day_start(self):
        dt = datetime(2026, 8, 19, 20, 0, tzinfo=UTC)  # Wednesday 20:00
        snapped = lead_service._snap_to_window(dt)
        assert snapped.hour == 9
        assert snapped.date() == (dt + timedelta(days=1)).date()

    def test_pushes_weekend_to_monday(self):
        dt = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)  # Saturday
        snapped = lead_service._snap_to_window(dt)
        assert snapped.weekday() == 0  # Monday
        assert snapped.hour == 9


class TestComputeNextAttempt:
    def test_first_failure_backs_off_one_hour(self):
        now = datetime(2026, 8, 19, 10, 0, tzinfo=UTC)
        next_at = lead_service.compute_next_attempt(1, now, "UTC")
        assert next_at == now + timedelta(hours=1)

    def test_second_failure_backs_off_three_hours(self):
        now = datetime(2026, 8, 19, 10, 0, tzinfo=UTC)
        next_at = lead_service.compute_next_attempt(2, now, "UTC")
        assert next_at == now + timedelta(hours=3)

    def test_third_failure_lands_next_morning(self):
        now = datetime(2026, 8, 19, 15, 0, tzinfo=UTC)  # already past 09:00 today
        next_at = lead_service.compute_next_attempt(3, now, "UTC")
        assert next_at.hour == 9
        assert next_at.date() == (now + timedelta(days=1)).date()

    def test_fourth_failure_lands_same_afternoon_if_still_ahead(self):
        now = datetime(2026, 8, 19, 10, 0, tzinfo=UTC)  # before 14:00
        next_at = lead_service.compute_next_attempt(4, now, "UTC")
        assert next_at.hour == 14
        assert next_at.date() == now.date()

    def test_result_always_lands_inside_business_hours(self):
        # A late-Friday failure must not schedule into the weekend.
        now = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)  # Friday 17:30
        for attempt in range(1, 6):
            next_at = lead_service.compute_next_attempt(attempt, now, "UTC")
            local = next_at.astimezone(UTC)
            assert local.weekday() < 5
            assert 9 <= local.hour < 18


@pytest.fixture
def placed_calls(monkeypatch) -> list[dict]:
    """Capture what would have been dialed instead of spending a real, billed call —
    same convention as test_prospects.py's placed_calls fixture, patched at the module
    reference lead_service actually calls through.
    """
    calls: list[dict] = []

    async def fake_place_test_call(
        db, agent_id, tenant_id, to_number, system_prompt_override=None, lead_id=None
    ):
        calls.append(
            {
                "agent_id": agent_id,
                "to_number": to_number,
                "prompt": system_prompt_override,
                "lead_id": lead_id,
            }
        )
        return {
            "call_id": f"mock_call_{len(calls)}",
            "from_number": "+10000000000",
            "status": "dialing",
        }

    from backend.services import test_call_service

    monkeypatch.setattr(test_call_service, "place_test_call", fake_place_test_call)
    return calls


@pytest.mark.asyncio
async def test_dispatch_scheduled_places_call_and_marks_in_flight(
    db_session, tenant_id, placed_calls
):
    agent = await _agent(db_session, tenant_id)
    lead = await _lead(db_session, tenant_id, agent_id=agent.id)

    await lead_service.dispatch_scheduled(db_session, lead)

    assert lead.retry_state == "in_flight"
    assert lead.attempt_count == 1
    assert lead.last_attempt_at is not None
    assert placed_calls[0]["to_number"] == lead.phone
    assert placed_calls[0]["lead_id"] == lead.id


@pytest.mark.asyncio
async def test_dispatch_scheduled_injects_lead_context_and_notes(
    db_session, tenant_id, placed_calls
):
    agent = await _agent(db_session, tenant_id)
    lead = await _lead(
        db_session,
        tenant_id,
        agent_id=agent.id,
        service_requested="Boiler repair",
        request_text="Boiler stopped working, need someone this week",
        notes="Best reached after 5pm.",
    )

    await lead_service.dispatch_scheduled(db_session, lead)

    prompt = placed_calls[0]["prompt"]
    assert "[ROLE] You are Alex." in prompt  # base script preserved
    assert "Boiler repair" in prompt
    assert "Boiler stopped working" in prompt
    assert "Best reached after 5pm." in prompt


@pytest.mark.asyncio
async def test_dispatch_scheduled_without_agent_is_a_failed_attempt_not_a_crash(
    db_session, tenant_id, placed_calls
):
    lead = await _lead(db_session, tenant_id)  # no agent_id
    await lead_service.start_lead(db_session, lead.id, tenant_id)

    await lead_service.dispatch_scheduled(db_session, lead)

    assert placed_calls == []
    assert lead.attempt_count == 1
    assert lead.retry_state == "scheduled"  # backed off, not stuck or crashed
    assert lead.last_outcome == "dispatch_error: no agent assigned"


@pytest.mark.asyncio
async def test_call_lead_now_requires_phone_and_agent(db_session, tenant_id, placed_calls):
    lead = await _lead(db_session, tenant_id)  # has phone, no agent

    with pytest.raises(lead_service.LeadDispatchError, match="No agent assigned"):
        await lead_service.call_lead_now(db_session, lead.id, tenant_id)


@pytest.mark.asyncio
async def test_evaluate_call_outcome_success_stops_retrying(db_session, tenant_id, monkeypatch):
    from backend.services import test_call_service

    async def fake_place_test_call(db, agent_id, tenant_id, to_number, **kwargs):
        call = await call_service.create_outbound_call_record(
            db, tenant_id, agent_id, "ext_success_1", to_number, lead_id=kwargs.get("lead_id")
        )
        return {"call_id": call.external_id, "from_number": "+1", "status": "dialing"}

    monkeypatch.setattr(test_call_service, "place_test_call", fake_place_test_call)

    agent = await _agent(db_session, tenant_id)
    lead = await _lead(db_session, tenant_id, agent_id=agent.id)
    await lead_service.dispatch_scheduled(db_session, lead)
    assert lead.retry_state == "in_flight"

    call = await call_service.get_call_by_external_id(db_session, "ext_success_1")
    await call_service.record_turns(
        db_session,
        call,
        [
            {"role": "agent", "text": "Hi, is now a good time?"},
            {"role": "caller", "text": "Sure, go ahead."},
        ],
    )
    call.status = "resolved"
    await db_session.commit()

    await lead_service.evaluate_call_outcome(db_session, call)

    refreshed = await lead_service.get_lead(db_session, lead.id, tenant_id)
    assert refreshed.retry_state == "succeeded"
    assert refreshed.status == "contacted"
    assert refreshed.next_attempt_at is None


@pytest.mark.asyncio
async def test_evaluate_call_outcome_no_caller_turns_is_treated_as_failure(
    db_session, tenant_id, monkeypatch
):
    """A resolved call with zero caller turns (voicemail, instant hangup) is NOT a
    success — the operator asked for "human answered and talked"."""
    from backend.services import test_call_service

    async def fake_place_test_call(db, agent_id, tenant_id, to_number, **kwargs):
        call = await call_service.create_outbound_call_record(
            db, tenant_id, agent_id, "ext_voicemail_1", to_number, lead_id=kwargs.get("lead_id")
        )
        return {"call_id": call.external_id, "from_number": "+1", "status": "dialing"}

    monkeypatch.setattr(test_call_service, "place_test_call", fake_place_test_call)

    agent = await _agent(db_session, tenant_id)
    lead = await _lead(db_session, tenant_id, agent_id=agent.id, timezone="UTC")
    await lead_service.dispatch_scheduled(db_session, lead)

    call = await call_service.get_call_by_external_id(db_session, "ext_voicemail_1")
    call.status = "resolved"
    await db_session.commit()

    await lead_service.evaluate_call_outcome(db_session, call)

    refreshed = await lead_service.get_lead(db_session, lead.id, tenant_id)
    assert refreshed.retry_state == "scheduled"
    assert refreshed.next_attempt_at is not None


@pytest.mark.asyncio
async def test_evaluate_call_outcome_is_idempotent_across_two_terminal_events(
    db_session, tenant_id, monkeypatch
):
    """Retell fires call_ended then call_analyzed for the same call — both reach a
    terminal status, both call evaluate_call_outcome. The second must be a no-op."""
    from backend.services import test_call_service

    async def fake_place_test_call(db, agent_id, tenant_id, to_number, **kwargs):
        call = await call_service.create_outbound_call_record(
            db, tenant_id, agent_id, "ext_double_1", to_number, lead_id=kwargs.get("lead_id")
        )
        return {"call_id": call.external_id, "from_number": "+1", "status": "dialing"}

    monkeypatch.setattr(test_call_service, "place_test_call", fake_place_test_call)

    agent = await _agent(db_session, tenant_id)
    lead = await _lead(db_session, tenant_id, agent_id=agent.id, timezone="UTC")
    await lead_service.dispatch_scheduled(db_session, lead)

    call = await call_service.get_call_by_external_id(db_session, "ext_double_1")
    call.status = "failed"
    await db_session.commit()

    await lead_service.evaluate_call_outcome(db_session, call)
    after_first = await lead_service.get_lead(db_session, lead.id, tenant_id)
    assert after_first.attempt_count == 1
    first_next_attempt = after_first.next_attempt_at

    # Second terminal event for the same call — retry_state is no longer in_flight.
    await lead_service.evaluate_call_outcome(db_session, call)
    after_second = await lead_service.get_lead(db_session, lead.id, tenant_id)
    assert after_second.attempt_count == 1  # unchanged — not double-counted
    assert after_second.next_attempt_at == first_next_attempt


@pytest.mark.asyncio
async def test_exhausted_after_max_attempts(db_session, tenant_id):
    lead = await _lead(db_session, tenant_id, timezone="UTC")
    lead.attempt_count = 5  # the 5th attempt was just placed and has now failed
    lead.retry_state = "in_flight"
    await db_session.commit()

    await lead_service.advance_after_failure(db_session, lead, "failed")

    assert lead.attempt_count == 5  # advance_after_failure doesn't increment itself
    assert lead.retry_state == "exhausted"
    assert lead.next_attempt_at is None


@pytest.mark.asyncio
async def test_paused_mid_call_is_not_re_armed_by_a_late_outcome(
    db_session, tenant_id, monkeypatch
):
    """The operator pauses a lead while its call is still in flight; the call later
    resolves. evaluate_call_outcome must respect the pause, not silently re-schedule."""
    from backend.services import test_call_service

    async def fake_place_test_call(db, agent_id, tenant_id, to_number, **kwargs):
        call = await call_service.create_outbound_call_record(
            db, tenant_id, agent_id, "ext_paused_1", to_number, lead_id=kwargs.get("lead_id")
        )
        return {"call_id": call.external_id, "from_number": "+1", "status": "dialing"}

    monkeypatch.setattr(test_call_service, "place_test_call", fake_place_test_call)

    agent = await _agent(db_session, tenant_id)
    lead = await _lead(db_session, tenant_id, agent_id=agent.id, timezone="UTC")
    await lead_service.dispatch_scheduled(db_session, lead)

    lead.retry_state = "paused"
    lead.next_attempt_at = None
    await db_session.commit()

    call = await call_service.get_call_by_external_id(db_session, "ext_paused_1")
    call.status = "failed"
    await db_session.commit()

    await lead_service.evaluate_call_outcome(db_session, call)

    refreshed = await lead_service.get_lead(db_session, lead.id, tenant_id)
    assert refreshed.retry_state == "paused"
    assert refreshed.next_attempt_at is None
