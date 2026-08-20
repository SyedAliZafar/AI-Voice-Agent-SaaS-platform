"""Abstract adapter for voice platforms (Retell AI, Vapi AI, etc).

ADR-002: This abstraction means adding a third platform is a new adapter
file, not a rewrite of call handling logic. Every platform-specific SDK
call goes through one of these adapters — never call retell/vapi SDKs
directly from routers or generic services.
"""

from abc import ABC, abstractmethod
from typing import Any


class VoicePlatformAdapter(ABC):
    """Every voice platform integration implements this interface."""

    @abstractmethod
    async def create_agent(self, name: str, system_prompt: str, voice_config: dict) -> str:
        """Provision an agent on the platform. Returns the platform's agent ID."""
        ...

    @abstractmethod
    async def assign_phone_number(self, agent_external_id: str, number: str) -> None:
        """Attach a phone number to a platform agent."""
        ...

    @abstractmethod
    async def send_response(self, call_external_id: str, text: str) -> None:
        """Send the LLM's text response back to the platform for TTS + playback."""
        ...

    @abstractmethod
    def parse_webhook(self, payload: dict) -> dict[str, Any]:
        """Normalize a platform-specific webhook payload into a common shape:
        {event: str, call_id: str, transcript: str | None}
        """
        ...

    # -- Outbound test-calling -------------------------------------------
    # Not @abstractmethod: only Retell implements these for now (built-in-LLM
    # test calls). Default raises so a platform without support fails loudly
    # and explicitly, rather than the adapter being non-instantiable.

    async def create_llm(self, system_prompt: str) -> str:
        """Provision a platform-hosted LLM from a system prompt. Returns its external ID."""
        raise NotImplementedError(f"{type(self).__name__} does not support create_llm")

    async def update_llm(self, llm_external_id: str, system_prompt: str) -> None:
        """Push an updated system prompt to an already-provisioned platform LLM."""
        raise NotImplementedError(f"{type(self).__name__} does not support update_llm")

    async def import_twilio_number(
        self,
        number: str,
        termination_uri: str,
        sip_trunk_username: str,
        sip_trunk_password: str,
    ) -> None:
        """One-time setup: import a Twilio number so the platform can dial out from it."""
        raise NotImplementedError(f"{type(self).__name__} does not support import_twilio_number")

    async def create_outbound_call(
        self, from_number: str, to_number: str, agent_external_id: str
    ) -> str:
        """Place an outbound call. Returns the platform's call ID."""
        raise NotImplementedError(f"{type(self).__name__} does not support create_outbound_call")

    async def get_call(self, call_external_id: str) -> dict[str, Any]:
        """Fetch authoritative state for one call from the platform.

        Backs call_service.reconcile_call — the self-healing path for calls whose
        lifecycle webhook never arrived. Expected to return at least the platform's
        status plus, once terminal, duration/transcript/analysis.
        """
        raise NotImplementedError(f"{type(self).__name__} does not support get_call")

    async def stop_call(self, call_external_id: str) -> None:
        """Hang up a call that is currently live.

        The emergency stop — see RetellAdapter.stop_call. Implementations should treat
        "already ended" as success, since that is the state the caller asked for.
        """
        raise NotImplementedError(f"{type(self).__name__} does not support stop_call")

    async def list_live_calls(self, limit: int = 100) -> list[dict[str, Any]]:
        """Calls the platform currently considers unfinished (dialing or talking).

        Asked of the platform rather than our own `calls` table because a call whose
        webhook never arrived is stuck at in_progress locally — the emergency stop must
        not inherit that bug. Each entry carries at least the platform's call id.
        """
        raise NotImplementedError(f"{type(self).__name__} does not support list_live_calls")

    async def list_platform_agents(self, limit: int = 100) -> list[dict[str, Any]]:
        """Agents that exist on the platform itself, including ones built by hand in its
        dashboard and never seen by this backend (ADR-012).

        Read-only and live: the roster is fetched on demand rather than mirrored into our
        database, so the picker can't show an agent that was renamed or deleted upstream.
        Each entry is normalized to {external_id, name, voice_id, engine, updated_at} —
        `engine` being the platform's own response-engine kind, which is what tells an
        operator whether an agent runs on the platform's LLM or points back at us.
        """
        raise NotImplementedError(f"{type(self).__name__} does not support list_platform_agents")

    def verify_webhook_signature(self, raw_body: str, signature: str | None) -> bool:
        """Verify a platform webhook's signature over the raw request body.

        Default denies: a platform without a real implementation must not be treated as
        verified. Callers gate on their own settings flag before reaching this.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support verify_webhook_signature"
        )


def get_adapter(platform: str) -> VoicePlatformAdapter:
    """Factory — returns the correct adapter for an agent's configured platform."""
    from backend.services.retell_adapter import RetellAdapter
    from backend.services.vapi_adapter import VapiAdapter

    adapters: dict[str, type[VoicePlatformAdapter]] = {
        "retell": RetellAdapter,
        "vapi": VapiAdapter,
    }
    adapter_cls = adapters.get(platform)
    if not adapter_cls:
        raise ValueError(f"Unknown voice platform: {platform}")
    return adapter_cls()
