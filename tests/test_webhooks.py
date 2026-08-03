"""Tests for the Retell/Vapi webhook receivers.

Focus: webhooks must respond fast and never 500 on malformed/partial payloads — a
crashed webhook handler means a dropped call event.

Payload shape matters here more than it looks. Retell nests the call object
({"event": ..., "call": {"call_id": ...}}); an earlier version of the schema expected a
flat top-level call_id, so every real webhook 422'd and calls were never marked ended.
These tests use the real nested shape specifically so that regression can't come back.

Signature verification is on by default in production. The `unsigned_webhooks` fixture
turns it off so these tests can post hand-built payloads; test_signature_required covers
the enabled path.
"""

import uuid

import pytest

from backend.api import webhooks as webhooks_module
from backend.services import call_service


@pytest.fixture
def unsigned_webhooks(monkeypatch):
    """Allow unsigned webhook posts, as if RETELL_VERIFY_WEBHOOKS=false."""
    monkeypatch.setattr(webhooks_module.settings, "retell_verify_webhooks", False)


@pytest.mark.asyncio
async def test_retell_webhook_call_started(client, unsigned_webhooks):
    resp = await client.post(
        "/webhooks/retell",
        json={"event": "call_started", "call": {"call_id": "call_123"}},
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "received"}


@pytest.mark.asyncio
async def test_retell_call_ended_resolves_call_and_sets_duration(
    client, db_session, tenant_id, unsigned_webhooks
):
    """The regression this whole change exists for: a real-shaped call_ended must move
    the row out of in_progress."""
    call = await call_service.create_outbound_call_record(
        db_session, tenant_id, uuid.uuid4(), "call_ended_1", "+491701234567"
    )
    assert call.status == "in_progress"

    resp = await client.post(
        "/webhooks/retell",
        json={
            "event": "call_ended",
            "call": {
                "call_id": "call_ended_1",
                "call_status": "ended",
                "disconnection_reason": "user_hangup",
                "duration_ms": 42_000,
                "transcript": "Agent: Hi.\nUser: Hello.",
            },
        },
    )
    assert resp.status_code == 200

    updated = await call_service.get_call(db_session, call.id, tenant_id)
    assert updated.status == "resolved"
    assert updated.duration_sec == 42

    transcript = await call_service.get_transcript(db_session, call.id, tenant_id)
    assert transcript is not None
    assert "Hello" in transcript.full_text


@pytest.mark.asyncio
async def test_retell_call_transfer_marks_escalated(
    client, db_session, tenant_id, unsigned_webhooks
):
    call = await call_service.create_outbound_call_record(
        db_session, tenant_id, uuid.uuid4(), "call_ended_2", "+491701234567"
    )

    await client.post(
        "/webhooks/retell",
        json={
            "event": "call_ended",
            "call": {
                "call_id": "call_ended_2",
                "call_status": "ended",
                "disconnection_reason": "call_transfer",
                "duration_ms": 8_000,
            },
        },
    )

    updated = await call_service.get_call(db_session, call.id, tenant_id)
    assert updated.status == "escalated"


@pytest.mark.asyncio
async def test_retell_dial_failure_marks_failed(client, db_session, tenant_id, unsigned_webhooks):
    call = await call_service.create_outbound_call_record(
        db_session, tenant_id, uuid.uuid4(), "call_ended_3", "+491701234567"
    )

    await client.post(
        "/webhooks/retell",
        json={
            "event": "call_ended",
            "call": {
                "call_id": "call_ended_3",
                "call_status": "ended",
                "disconnection_reason": "dial_no_answer",
            },
        },
    )

    updated = await call_service.get_call(db_session, call.id, tenant_id)
    assert updated.status == "failed"


@pytest.mark.asyncio
async def test_retell_call_analyzed_sets_sentiment(
    client, db_session, tenant_id, unsigned_webhooks
):
    call = await call_service.create_outbound_call_record(
        db_session, tenant_id, uuid.uuid4(), "call_analyzed_1", "+491701234567"
    )

    resp = await client.post(
        "/webhooks/retell",
        json={
            "event": "call_analyzed",
            "call": {
                "call_id": "call_analyzed_1",
                "call_status": "ended",
                "call_analysis": {"user_sentiment": "Positive"},
            },
        },
    )
    assert resp.status_code == 200

    updated = await call_service.get_call(db_session, call.id, tenant_id)
    assert updated.sentiment_score == 1.0


@pytest.mark.asyncio
async def test_retell_unknown_sentiment_leaves_score_unset(
    client, db_session, tenant_id, unsigned_webhooks
):
    call = await call_service.create_outbound_call_record(
        db_session, tenant_id, uuid.uuid4(), "call_analyzed_2", "+491701234567"
    )

    await client.post(
        "/webhooks/retell",
        json={
            "event": "call_analyzed",
            "call": {
                "call_id": "call_analyzed_2",
                "call_status": "ended",
                "call_analysis": {"user_sentiment": "Unknown"},
            },
        },
    )

    updated = await call_service.get_call(db_session, call.id, tenant_id)
    assert updated.sentiment_score is None


@pytest.mark.asyncio
async def test_retell_webhook_unknown_call_is_graceful(client, unsigned_webhooks):
    """An unmatched call_id must no-op, not 500 — ADR-005."""
    resp = await client.post(
        "/webhooks/retell",
        json={
            "event": "call_ended",
            "call": {"call_id": "never_seen", "call_status": "ended"},
        },
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_retell_webhook_rejects_missing_call_object(client, unsigned_webhooks):
    resp = await client.post("/webhooks/retell", json={"event": "call_ended"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_retell_webhook_rejects_missing_event(client, unsigned_webhooks):
    resp = await client.post("/webhooks/retell", json={"call": {"call_id": "call_123"}})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_signature_required_when_verification_enabled(client, monkeypatch):
    """With verification on (the production default), an unsigned post is rejected."""
    monkeypatch.setattr(webhooks_module.settings, "retell_verify_webhooks", True)

    resp = await client.post(
        "/webhooks/retell",
        json={"event": "call_started", "call": {"call_id": "call_123"}},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_vapi_webhook_call_start(client):
    resp = await client.post(
        "/webhooks/vapi",
        json={"type": "call-start", "call": {"id": "vapi_call_456"}},
    )
    assert resp.status_code == 200
