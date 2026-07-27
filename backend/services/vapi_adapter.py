"""Vapi AI specific implementation of VoicePlatformAdapter.

Docs: https://docs.vapi.ai — fill in real SDK calls once you have API access.
"""

from typing import Any

import httpx

from backend.config import get_settings
from backend.services.voice_platform import VoicePlatformAdapter

settings = get_settings()
BASE_URL = "https://api.vapi.ai"


class VapiAdapter(VoicePlatformAdapter):
    def __init__(self) -> None:
        self.headers = {"Authorization": f"Bearer {settings.vapi_api_key}"}

    async def create_agent(self, name: str, system_prompt: str, voice_config: dict) -> str:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{BASE_URL}/assistant",
                headers=self.headers,
                json={
                    "name": name,
                    "model": {"provider": "anthropic", "model": "claude-sonnet-4-6"},
                    "voice": voice_config,
                },
            )
            resp.raise_for_status()
            return resp.json()["id"]

    async def assign_phone_number(self, agent_external_id: str, number: str) -> None:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{BASE_URL}/phone-number",
                headers=self.headers,
                json={"number": number, "assistantId": agent_external_id},
            )
            resp.raise_for_status()

    async def send_response(self, call_external_id: str, text: str) -> None:
        # Vapi handles LLM responses via its own model config by default;
        # if using a custom LLM integration, this posts to Vapi's server-url
        # webhook response format instead. Wire up per your integration mode.
        raise NotImplementedError("Wire up Vapi's response protocol here")

    def parse_webhook(self, payload: dict) -> dict[str, Any]:
        call = payload.get("call", {})
        return {
            "event": payload.get("type"),
            "call_id": call.get("id"),
            "transcript": payload.get("transcript"),
        }
