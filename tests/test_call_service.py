"""Tests for call_service — creation at outbound-placement time, and the
webhook-driven update paths (found-by-external_id vs. graceful not-found).
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from backend.services import call_service


@pytest.mark.asyncio
async def test_create_outbound_call_record_sets_in_progress(db_session, tenant_id):
    agent_id = uuid.uuid4()

    call = await call_service.create_outbound_call_record(
        db_session, tenant_id, agent_id, "retell_call_1", "+491701234567"
    )

    assert call.status == "in_progress"
    assert call.external_id == "retell_call_1"
    assert call.caller_number == "+491701234567"
    assert call.tenant_id == tenant_id
    assert call.agent_id == agent_id

    fetched = await call_service.get_call(db_session, call.id, tenant_id)
    assert fetched is not None
    assert fetched.external_id == "retell_call_1"


@pytest.mark.asyncio
async def test_handle_transcript_update_creates_transcript_for_known_call(db_session, tenant_id):
    call = await call_service.create_outbound_call_record(
        db_session, tenant_id, uuid.uuid4(), "retell_call_2", "+491701234567"
    )

    await call_service.handle_transcript_update(db_session, "retell_call_2", "Hello there")

    transcript = await call_service.get_transcript(db_session, call.id, tenant_id)
    assert transcript is not None
    assert transcript.full_text == "Hello there"


@pytest.mark.asyncio
async def test_handle_transcript_update_updates_existing_transcript(db_session, tenant_id):
    call = await call_service.create_outbound_call_record(
        db_session, tenant_id, uuid.uuid4(), "retell_call_3", "+491701234567"
    )
    await call_service.handle_transcript_update(db_session, "retell_call_3", "First")
    await call_service.handle_transcript_update(db_session, "retell_call_3", "First and second")

    transcript = await call_service.get_transcript(db_session, call.id, tenant_id)
    assert transcript.full_text == "First and second"


@pytest.mark.asyncio
async def test_handle_transcript_update_noop_for_unknown_call(db_session):
    # Must not raise — an inbound/unrecognized call_id is a graceful no-op.
    await call_service.handle_transcript_update(db_session, "unknown_call", "Hello")


@pytest.mark.asyncio
async def test_handle_call_ended_marks_resolved_and_sets_duration(db_session, tenant_id):
    call = await call_service.create_outbound_call_record(
        db_session, tenant_id, uuid.uuid4(), "retell_call_4", "+491701234567"
    )
    # Backdate started_at so the wall-clock fallback yields a non-zero duration.
    call.started_at = datetime.now(UTC) - timedelta(seconds=42)
    await db_session.commit()

    # No payload — the pre-webhook_url legacy path. Must still conclude the call.
    await call_service.handle_call_ended(db_session, "retell_call_4")

    updated = await call_service.get_call(db_session, call.id, tenant_id)
    assert updated.status == "resolved"
    assert updated.duration_sec >= 42


@pytest.mark.asyncio
async def test_handle_call_ended_prefers_platform_duration(db_session, tenant_id):
    """Retell's duration_ms wins over wall-clock arithmetic — reconcile can run long
    after a call ended, when `now - started_at` would be nonsense."""
    call = await call_service.create_outbound_call_record(
        db_session, tenant_id, uuid.uuid4(), "retell_call_5", "+491701234567"
    )
    call.started_at = datetime.now(UTC) - timedelta(days=2)
    await db_session.commit()

    await call_service.handle_call_ended(
        db_session,
        "retell_call_5",
        {"call_status": "ended", "disconnection_reason": "user_hangup", "duration_ms": 31_000},
    )

    updated = await call_service.get_call(db_session, call.id, tenant_id)
    assert updated.duration_sec == 31


class _StubAdapter:
    """Stands in for RetellAdapter.get_call in reconcile tests."""

    def __init__(self, payload: dict | None = None, raises: bool = False):
        self.payload = payload or {}
        self.raises = raises

    async def get_call(self, call_external_id: str) -> dict:
        if self.raises:
            raise RuntimeError("platform unreachable")
        return self.payload


@pytest.mark.asyncio
async def test_reconcile_unsticks_a_call_whose_webhook_never_arrived(db_session, tenant_id):
    """The core of the self-healing path: no call_ended was ever delivered, so the row
    is stranded at in_progress until reconcile pulls the real state."""
    call = await call_service.create_outbound_call_record(
        db_session, tenant_id, uuid.uuid4(), "stranded_1", "+491701234567"
    )
    assert call.status == "in_progress"

    adapter = _StubAdapter(
        {
            "call_status": "ended",
            "disconnection_reason": "user_hangup",
            "duration_ms": 17_000,
            "transcript": "Agent: Hi.",
            "call_analysis": {"user_sentiment": "Negative"},
        }
    )

    changed = await call_service.reconcile_call(db_session, call, adapter)

    assert changed is True
    updated = await call_service.get_call(db_session, call.id, tenant_id)
    assert updated.status == "resolved"
    assert updated.duration_sec == 17
    assert updated.sentiment_score == 0.0


@pytest.mark.asyncio
async def test_reconcile_leaves_still_ongoing_calls_alone(db_session, tenant_id):
    call = await call_service.create_outbound_call_record(
        db_session, tenant_id, uuid.uuid4(), "ongoing_1", "+491701234567"
    )

    changed = await call_service.reconcile_call(
        db_session, call, _StubAdapter({"call_status": "ongoing"})
    )

    assert changed is False
    updated = await call_service.get_call(db_session, call.id, tenant_id)
    assert updated.status == "in_progress"


@pytest.mark.asyncio
async def test_reconcile_survives_platform_errors(db_session, tenant_id):
    """One unreachable call must not abort a bulk sync."""
    call = await call_service.create_outbound_call_record(
        db_session, tenant_id, uuid.uuid4(), "err_1", "+491701234567"
    )

    changed = await call_service.reconcile_call(db_session, call, _StubAdapter(raises=True))

    assert changed is False
    updated = await call_service.get_call(db_session, call.id, tenant_id)
    assert updated.status == "in_progress"


@pytest.mark.asyncio
async def test_reconcile_stale_calls_is_tenant_scoped(db_session, tenant_id, other_tenant_id):
    """ADR-001: syncing must never touch another tenant's calls."""
    mine = await call_service.create_outbound_call_record(
        db_session, tenant_id, uuid.uuid4(), "mine_1", "+491701234567"
    )
    theirs = await call_service.create_outbound_call_record(
        db_session, other_tenant_id, uuid.uuid4(), "theirs_1", "+491709999999"
    )

    adapter = _StubAdapter(
        {"call_status": "ended", "disconnection_reason": "user_hangup", "duration_ms": 5_000}
    )
    updated_count = await call_service.reconcile_stale_calls(db_session, tenant_id, adapter)

    assert updated_count == 1
    assert (await call_service.get_call(db_session, mine.id, tenant_id)).status == "resolved"
    assert (
        await call_service.get_call(db_session, theirs.id, other_tenant_id)
    ).status == "in_progress"


@pytest.mark.asyncio
async def test_handle_call_ended_noop_for_unknown_call(db_session):
    # Must not raise.
    await call_service.handle_call_ended(db_session, "unknown_call")


@pytest.mark.asyncio
async def test_handle_call_started_never_raises():
    # Purely a log-and-return no-op today (see module docstring) — just must not crash.
    await call_service.handle_call_started("some_call_id", platform="retell")
