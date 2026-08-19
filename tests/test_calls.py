"""Tests for call listing and filtering logic."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import httpx
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


@pytest.mark.asyncio
async def test_end_call_endpoint_hangs_up(client, db_session, tenant_id, auth_headers):
    """The UI-facing emergency stop. The adapter is patched at its import site in the
    router, so the test never reaches Retell."""
    call = await call_service.create_outbound_call_record(
        db_session, tenant_id, uuid.uuid4(), "api_live_1", "+491701234567"
    )

    adapter = AsyncMock()
    adapter.get_call.return_value = {
        "call_status": "ended",
        "disconnection_reason": "agent_hangup",
        "duration_ms": 4_000,
    }

    with patch("backend.api.calls.RetellAdapter", return_value=adapter):
        resp = await client.post(f"/api/calls/{call.id}/end", headers=auth_headers)

    assert resp.status_code == 200
    adapter.stop_call.assert_awaited_once_with("api_live_1")


@pytest.mark.asyncio
async def test_end_call_endpoint_is_tenant_scoped(
    client, db_session, other_tenant_id, auth_headers
):
    """ADR-001: one tenant must never be able to hang up another's call. Reads as 404
    rather than 403 so call ids stay non-enumerable."""
    theirs = await call_service.create_outbound_call_record(
        db_session, other_tenant_id, uuid.uuid4(), "api_theirs_1", "+491709999999"
    )

    adapter = AsyncMock()
    with patch("backend.api.calls.RetellAdapter", return_value=adapter):
        resp = await client.post(f"/api/calls/{theirs.id}/end", headers=auth_headers)

    assert resp.status_code == 404
    adapter.stop_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_end_call_endpoint_reports_a_failed_hangup_as_502(
    client, db_session, tenant_id, auth_headers
):
    """Never report success for a hangup that didn't happen — the operator would walk
    away believing a live call was stopped while it is still talking."""
    call = await call_service.create_outbound_call_record(
        db_session, tenant_id, uuid.uuid4(), "api_live_2", "+491701234567"
    )

    adapter = AsyncMock()
    adapter.stop_call.side_effect = httpx.ConnectError("no route to Retell")

    with patch("backend.api.calls.RetellAdapter", return_value=adapter):
        resp = await client.post(f"/api/calls/{call.id}/end", headers=auth_headers)

    assert resp.status_code == 502
