"""Tests for call listing and filtering logic."""

import uuid
from datetime import UTC, datetime

import pytest

from backend.models.call import Call
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
async def test_get_call_not_found(db_session):
    call = await call_service.get_call(db_session, uuid.uuid4())
    assert call is None
