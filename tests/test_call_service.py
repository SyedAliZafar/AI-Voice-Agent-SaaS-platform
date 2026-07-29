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
    # Backdate started_at so duration_sec is meaningfully non-zero.
    call.started_at = datetime.now(UTC) - timedelta(seconds=42)
    await db_session.commit()

    await call_service.handle_call_ended(db_session, "retell_call_4")

    updated = await call_service.get_call(db_session, call.id, tenant_id)
    assert updated.status == "resolved"
    assert updated.duration_sec >= 42


@pytest.mark.asyncio
async def test_handle_call_ended_noop_for_unknown_call(db_session):
    # Must not raise.
    await call_service.handle_call_ended(db_session, "unknown_call")


@pytest.mark.asyncio
async def test_handle_call_started_never_raises():
    # Purely a log-and-return no-op today (see module docstring) — just must not crash.
    await call_service.handle_call_started("some_call_id", platform="retell")
