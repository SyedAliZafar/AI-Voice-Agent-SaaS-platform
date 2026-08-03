"""Retell AI specific implementation of VoicePlatformAdapter.

Docs: https://docs.retellai.com — fill in real SDK calls here once you
have API access. Shape kept intentionally thin so it's obvious what to
replace with real HTTP calls to Retell's API.
"""

import logging
from typing import Any

import httpx

from backend.config import get_settings
from backend.services.voice_platform import VoicePlatformAdapter

logger = logging.getLogger(__name__)
settings = get_settings()
BASE_URL = "https://api.retellai.com"


class RetellAdapter(VoicePlatformAdapter):
    def __init__(self) -> None:
        self.headers = {"Authorization": f"Bearer {settings.retell_api_key}"}

    async def create_agent(self, name: str, system_prompt: str, voice_config: dict) -> str:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{BASE_URL}/create-agent",
                headers=self.headers,
                json={
                    "agent_name": name,
                    "response_engine": {"type": "custom-llm"},
                    "voice_id": voice_config.get("voice_id", "default"),
                },
            )
            resp.raise_for_status()
            return resp.json()["agent_id"]

    async def create_agent_with_llm(
        self, name: str, llm_id: str, voice_id: str, webhook_url: str | None = None
    ) -> str:
        """Provision an agent backed by a Retell-hosted LLM (retell-llm), used for outbound
        test calls where Retell's own LLM runs the conversation — no custom-LLM websocket
        needed. See test_call_service.place_test_call.

        `webhook_url` registers a per-agent webhook so call_started/call_ended/call_analyzed
        reach us. Without it Retell falls back to the account-level webhook configured in
        the dashboard — and if that isn't set either, no events arrive at all and calls
        stay at status="in_progress" forever. Optional because the hosted path is meant to
        work with no tunnel; POST /api/calls/sync covers the resulting gap.
        """
        body: dict[str, Any] = {
            "agent_name": name,
            "response_engine": {"type": "retell-llm", "llm_id": llm_id},
            "voice_id": voice_id,
        }
        if webhook_url:
            body["webhook_url"] = webhook_url

        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{BASE_URL}/create-agent", headers=self.headers, json=body)
            resp.raise_for_status()
            return resp.json()["agent_id"]

    async def create_agent_with_custom_llm(
        self,
        name: str,
        llm_websocket_url: str,
        voice_id: str,
        webhook_url: str | None = None,
    ) -> str:
        """Provision an agent backed by OUR Custom LLM WebSocket (ADR-003) — Retell dials
        `llm_websocket_url` (appending the call's own call_id itself, per Retell's
        protocol: docs.retellai.com/api-references/llm-websocket) and relays transcript
        turns to backend/api/retell_ws.py, which answers using DeepSeek + server-side
        tools. Contrast with create_agent_with_llm, which uses Retell's own hosted LLM.
        """
        body: dict[str, Any] = {
            "agent_name": name,
            "response_engine": {
                "type": "custom-llm",
                "llm_websocket_url": llm_websocket_url,
            },
            "voice_id": voice_id,
        }
        if webhook_url:
            body["webhook_url"] = webhook_url

        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{BASE_URL}/create-agent", headers=self.headers, json=body)
            resp.raise_for_status()
            return resp.json()["agent_id"]

    async def create_llm(self, system_prompt: str) -> str:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{BASE_URL}/create-retell-llm",
                headers=self.headers,
                json={"general_prompt": system_prompt},
            )
            resp.raise_for_status()
            return resp.json()["llm_id"]

    async def update_llm(self, llm_external_id: str, system_prompt: str) -> None:
        async with httpx.AsyncClient() as client:
            resp = await client.patch(
                f"{BASE_URL}/update-retell-llm/{llm_external_id}",
                headers=self.headers,
                json={"general_prompt": system_prompt},
            )
            resp.raise_for_status()

    async def import_twilio_number(
        self,
        number: str,
        termination_uri: str,
        sip_trunk_username: str,
        sip_trunk_password: str,
    ) -> None:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{BASE_URL}/import-phone-number",
                headers=self.headers,
                json={
                    "phone_number": number,
                    "termination_uri": termination_uri,
                    "sip_trunk_auth_username": sip_trunk_username,
                    "sip_trunk_auth_password": sip_trunk_password,
                },
            )
            resp.raise_for_status()

    async def get_call(self, call_external_id: str) -> dict[str, Any]:
        """Fetch authoritative state for one call.

        The reconcile path's data source (call_service.reconcile_call): returns
        call_status, disconnection_reason, duration_ms, transcript and call_analysis —
        everything needed to conclude a call whose webhook never arrived.
        """
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{BASE_URL}/v2/get-call/{call_external_id}", headers=self.headers
            )
            resp.raise_for_status()
            return dict(resp.json())

    async def create_outbound_call(
        self, from_number: str, to_number: str, agent_external_id: str
    ) -> str:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{BASE_URL}/v2/create-phone-call",
                headers=self.headers,
                json={
                    "from_number": from_number,
                    "to_number": to_number,
                    "override_agent_id": agent_external_id,
                },
            )
            resp.raise_for_status()
            return resp.json()["call_id"]

    async def assign_phone_number(self, agent_external_id: str, number: str) -> None:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{BASE_URL}/import-phone-number",
                headers=self.headers,
                json={"phone_number": number, "agent_id": agent_external_id},
            )
            resp.raise_for_status()

    async def send_response(self, call_external_id: str, text: str) -> None:
        # Retell's custom-LLM websocket protocol expects streamed response
        # chunks over the active call's websocket connection, not a REST call.
        # Implement via the LLM websocket handler when wiring this up for real.
        raise NotImplementedError("Wire up Retell's custom-LLM websocket protocol here")

    def verify_webhook_signature(self, raw_body: str, signature: str | None) -> bool:
        """Verify Retell's X-Retell-Signature header over the RAW request body.

        Delegates to the official SDK rather than reimplementing the HMAC. The header is
        `v={timestamp},d={digest}` (HMAC-SHA256 keyed on the API key), and a subtly wrong
        reimplementation would reject every webhook — which presents exactly like the
        "calls stuck in_progress" bug this was written alongside. Not worth hand-rolling.

        Must be given the raw body bytes as received: re-serializing the parsed JSON
        changes whitespace/key order and the digest will not match.

        Operational note: Retell only signs with an API key that has the webhook badge in
        their dashboard. If verification fails for every event, check that RETELL_API_KEY
        is that key.
        """
        if not signature:
            return False

        # Imported lazily — only needed on the webhook path. Note this lives at
        # retell.lib.verify in the v5 SDK; Retell's own docs still show a
        # `Retell.verify(...)` classmethod that no longer exists.
        from retell.lib import verify as retell_verify

        try:
            return bool(
                retell_verify(
                    body=raw_body, api_key=settings.retell_api_key, signature=signature
                )
            )
        except Exception:
            logger.warning("retell signature verification raised", exc_info=True)
            return False

    def parse_webhook(self, payload: dict) -> dict[str, Any]:
        """Normalize a Retell webhook payload. Retell nests the call object — `call_id`
        and `transcript` live under payload["call"], never at the top level.
        """
        call = payload.get("call") or {}
        return {
            "event": payload.get("event"),
            "call_id": call.get("call_id"),
            "transcript": call.get("transcript"),
        }
