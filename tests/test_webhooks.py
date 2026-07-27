"""Tests for the Retell/Vapi webhook receivers.

Focus: webhooks must respond fast and never 500 on malformed/partial
payloads — a crashed webhook handler means a dropped call event.
"""

import pytest


@pytest.mark.asyncio
async def test_retell_webhook_call_started(client):
    resp = await client.post(
        "/webhooks/retell",
        json={"event": "call_started", "call_id": "call_123"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "received"}


@pytest.mark.asyncio
async def test_retell_webhook_transcript_update(client):
    resp = await client.post(
        "/webhooks/retell",
        json={"event": "transcript_update", "call_id": "call_123", "transcript": "Hello"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_vapi_webhook_call_start(client):
    resp = await client.post(
        "/webhooks/vapi",
        json={"type": "call-start", "call": {"id": "vapi_call_456"}},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_webhook_rejects_missing_required_field(client):
    resp = await client.post("/webhooks/retell", json={"call_id": "call_123"})
    assert resp.status_code == 422  # missing required "event" field
