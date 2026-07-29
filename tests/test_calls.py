"""Tests for call listing and filtering logic."""

import uuid
from datetime import UTC, datetime

import pytest

from backend.models.call import Call, Transcript
from backend.services import call_service


@pytest.mark.asyncio
async def test_list_calls_filters_by_status(db_session, tenant_id):
    agent_id = uuid.uuid4()
    db_session.add_all(
        [
            Call(
                tenant_id=tenant_id,
                agent_id=agent_id,
                caller_number="+15551234567",
                status="resolved",
                started_at=datetime.now(UTC),
            ),
            Call(
                tenant_id=tenant_id,
                agent_id=agent_id,
                caller_number="+15559876543",
                status="escalated",
                started_at=datetime.now(UTC),
            ),
        ]
    )
    await db_session.commit()

    resolved_calls = await call_service.list_calls(
        db_session, tenant_id, agent_id=None, status="resolved", limit=50, offset=0
    )

    assert len(resolved_calls) == 1
    assert resolved_calls[0].status == "resolved"


@pytest.mark.asyncio
async def test_get_call_not_found(db_session, tenant_id):
    call = await call_service.get_call(db_session, uuid.uuid4(), tenant_id)
    assert call is None


@pytest.mark.asyncio
async def test_get_call_is_scoped_to_tenant(db_session, tenant_id, other_tenant_id):
    call = Call(
        tenant_id=tenant_id,
        agent_id=uuid.uuid4(),
        caller_number="+15551234567",
        status="resolved",
        started_at=datetime.now(UTC),
    )
    db_session.add(call)
    await db_session.commit()
    await db_session.refresh(call)

    assert await call_service.get_call(db_session, call.id, tenant_id) is not None
    assert await call_service.get_call(db_session, call.id, other_tenant_id) is None


@pytest.mark.asyncio
async def test_get_transcript_is_scoped_via_parent_call(db_session, tenant_id, other_tenant_id):
    """Transcript has no tenant_id of its own — isolation comes from the join to Call."""
    call = Call(
        tenant_id=tenant_id,
        agent_id=uuid.uuid4(),
        caller_number="+15551234567",
        status="resolved",
        started_at=datetime.now(UTC),
    )
    db_session.add(call)
    await db_session.commit()
    await db_session.refresh(call)

    db_session.add(Transcript(call_id=call.id, full_text="hello", turns=[]))
    await db_session.commit()

    assert await call_service.get_transcript(db_session, call.id, tenant_id) is not None
    assert await call_service.get_transcript(db_session, call.id, other_tenant_id) is None
