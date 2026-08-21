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

    async def update_llm(self, llm_external_id: str, system_prompt: str) -> bool:
        """Push an updated system prompt to an already-provisioned platform LLM.

        Returns False when the platform no longer has that LLM, so the caller can
        re-provision rather than stay pinned to a dead id — see RetellAdapter.update_llm.
        """
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
        self,
        from_number: str,
        to_number: str,
        agent_external_id: str,
        dynamic_variables: dict[str, str] | None = None,
    ) -> str:
        """Place an outbound call. Returns the platform's call ID.

        `dynamic_variables` fills placeholders in the agent's own prompt for this call
        only — the personalization channel for an agent whose prompt we don't own
        (ADR-012). Ignored by platforms without the concept.
        """
        raise NotImplementedError(f"{type(self).__name__} does not support create_outbound_call")

    async def create_web_call(
        self,
        agent_external_id: str,
        dynamic_variables: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """Open a browser-based call session. Returns at least {call_id, access_token}.

        The demo channel: audio runs between the viewer's browser and the platform, so
        there is no phone number, no telephony cost, and — unlike the custom-LLM path —
        nothing has to be publicly reachable on our side. The access token is a
        short-lived, call-scoped credential the browser SDK trades for a live mic
        session; it is not an account key.
        """
        raise NotImplementedError(f"{type(self).__name__} does not support create_web_call")

    async def get_agent_prompt(self, agent_external_id: str) -> dict[str, Any]:
        """The script a platform-native agent runs on, for inspection (ADR-012).

        Expected keys: engine, general_prompt, begin_message. Prompt fields may be empty
        when the platform has no single prompt string to report — `engine` tells the
        caller which case that is.
        """
        raise NotImplementedError(f"{type(self).__name__} does not support get_agent_prompt")

    async def get_agent_dynamic_variables(self, agent_external_id: str) -> list[str]:
        """Placeholder names a platform agent's prompt declares, sorted.

        Best-effort by nature — it reads a template we don't own. Return [] when the
        prompt can't be inspected rather than raising: not knowing must not block a dial
        that may need no variables at all.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support get_agent_dynamic_variables"
        )

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
