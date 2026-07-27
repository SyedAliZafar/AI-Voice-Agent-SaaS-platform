"""Retell AI specific implementation of VoicePlatformAdapter.

Docs: https://docs.retellai.com — fill in real SDK calls here once you
have API access. Shape kept intentionally thin so it's obvious what to
replace with real HTTP calls to Retell's API.
"""

from typing import Any

import httpx

from backend.config import get_settings
from backend.services.voice_platform import VoicePlatformAdapter

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

    async def create_agent_with_llm(self, name: str, llm_id: str, voice_id: str) -> str:
        """Provision an agent backed by a Retell-hosted LLM (retell-llm), used for outbound
        test calls where Retell's own LLM runs the conversation — no custom-LLM websocket
        needed. See test_call_service.place_test_call.
        """
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{BASE_URL}/create-agent",
                headers=self.headers,
                json={
                    "agent_name": name,
                    "response_engine": {"type": "retell-llm", "llm_id": llm_id},
                    "voice_id": voice_id,
                },
            )
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

    async def import_twilio_number(self, number: str, twilio_sid: str, twilio_token: str) -> None:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{BASE_URL}/import-phone-number",
                headers=self.headers,
                json={
                    "phone_number": number,
                    "termination_uri": "",
                    "sip_trunk_auth_username": twilio_sid,
                    "sip_trunk_auth_password": twilio_token,
                },
            )
            resp.raise_for_status()

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

    def parse_webhook(self, payload: dict) -> dict[str, Any]:
        return {
            "event": payload.get("event"),
            "call_id": payload.get("call_id"),
            "transcript": payload.get("transcript"),
        }
