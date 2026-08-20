"""Retell AI specific implementation of VoicePlatformAdapter.

Docs: https://docs.retellai.com — fill in real SDK calls here once you
have API access. Shape kept intentionally thin so it's obvious what to
replace with real HTTP calls to Retell's API.
"""

import logging
import re
from typing import Any

import httpx

from backend.config import get_settings
from backend.services.voice_platform import VoicePlatformAdapter

logger = logging.getLogger(__name__)
settings = get_settings()
BASE_URL = "https://api.retellai.com"

# Retell's ambient_sound enum, obtained from the API itself (create-agent's 400 for an
# invalid value names every accepted one) rather than guessed from docs or dashboard
# screenshots — the exact mistake that produced two prior sessions' worth of dashboard
# settings that were never real. Labels are ours; ids must match Retell's strings exactly.
# Retell's dynamic-variable placeholder syntax, as it appears in an agent's prompt:
# {{company_name}}, optionally spaced. Retell's dashboard builds its "Dynamic Variables"
# fill-in list the same way — by scanning the prompt — so this regex IS the contract;
# there is no endpoint that reports the names.
_DYNAMIC_VARIABLE_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")

AMBIENT_SOUND_CATALOG: list[dict[str, str]] = [
    {"id": "coffee-shop", "label": "Coffee shop"},
    {"id": "convention-hall", "label": "Convention hall"},
    {"id": "summer-outdoor", "label": "Summer outdoor"},
    {"id": "mountain-outdoor", "label": "Mountain outdoor"},
    {"id": "static-noise", "label": "Static noise"},
    {"id": "call-center", "label": "Call center"},
]


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
        begin_message_delay_ms: int | None = None,
        interruption_sensitivity: float | None = None,
        responsiveness: float | None = None,
        ambient_sound: str | None = None,
        expressive_mode: bool | None = None,
        expressive_emotion_tags: list[str] | None = None,
    ) -> str:
        """Provision an agent backed by OUR Custom LLM WebSocket (ADR-003) — Retell dials
        `llm_websocket_url` (appending the call's own call_id itself, per Retell's
        protocol: docs.retellai.com/api-references/llm-websocket) and relays transcript
        turns to backend/api/retell_ws.py, which answers using DeepSeek + server-side
        tools. Contrast with create_agent_with_llm, which uses Retell's own hosted LLM.

        begin_message_delay_ms holds the agent's opener after the call is answered
        (ADR-010). It has to be Retell's parameter rather than a sleep on our side: the
        websocket opens during call setup, so we can't tell ringing apart from pickup.

        interruption_sensitivity is the *other* barge-in control (0 = very hard to
        interrupt, 1 = stops instantly). retell_ws._should_let_turn_finish only governs
        whether WE cancel generation; this governs whether Retell stops speaking what we
        already sent. Left unset it defaults to 1.0 on Retell's side, which silently
        undoes the guard by chopping the audio anyway — see settings.

        responsiveness/ambient_sound/expressive_mode/expressive_emotion_tags are plain
        pass-throughs, no correctness properties of their own — see the matching
        settings.retell_* fields for why those defaults are what they are. They're
        parameters here rather than hardcoded so a caller (or a test) can still override
        them; test_call_service is the only real caller and always passes settings'
        values explicitly.
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
        if begin_message_delay_ms:
            body["begin_message_delay_ms"] = begin_message_delay_ms
        # `is not None`, not truthiness: 0.0 is a meaningful value for both fields
        # ("never interrupt" / "as patient as possible") and must not be dropped as
        # falsy.
        if interruption_sensitivity is not None:
            body["interruption_sensitivity"] = interruption_sensitivity
        if responsiveness is not None:
            body["responsiveness"] = responsiveness
        if ambient_sound is not None:
            body["ambient_sound"] = ambient_sound
        if expressive_mode is not None:
            body["enable_expressive_mode"] = expressive_mode
        if expressive_emotion_tags is not None:
            body["expressive_emotion_tags"] = expressive_emotion_tags

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

    async def stop_call(self, call_external_id: str) -> None:
        """Hang up a call that is happening right now.

        The emergency stop: an agent talking to the wrong person, looping on an IVR, or
        reading a broken prompt aloud has to be stoppable in seconds, and until this
        existed the only way was Retell's dashboard. See call_service.end_call for the
        path that also writes the call's terminal state, and scripts/kill_calls.py for
        the operator-facing version that works with no API server running.

        Idempotent from the caller's perspective — "already over" is the outcome the
        caller wanted, so it is not an error. Retell signals that two different ways,
        both verified against the live API:
          - 404 for a call id it doesn't know at all;
          - 400 "Can only stop an ongoing call." for one that has already ended.
        The 400 matters more than it looks: hanging up inherently races the call ending
        on its own, so without this a stop issued a second too late reports failure for
        a call that is, in fact, down.

        The 400 is matched on its message rather than the status code alone, so a genuine
        malformed-request 400 still surfaces. Every other status is a real failure (bad
        key, network) and must propagate — a silent failure here means someone believes a
        live call was killed when it is still talking.
        """
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{BASE_URL}/v2/stop-call/{call_external_id}", headers=self.headers
            )
            if resp.status_code == 404 or (resp.status_code == 400 and "ongoing call" in resp.text):
                logger.info(
                    "stop_call: call already ended or unknown to Retell",
                    extra={"call_external_id": call_external_id},
                )
                return
            resp.raise_for_status()

    async def list_live_calls(self, limit: int = 100) -> list[dict[str, Any]]:
        """Calls Retell currently considers live, newest first.

        Filters on `ongoing` alone. Retell's call_status enum is exactly
        {not_connected, ongoing, ended, error} — "not_connected" is a call that never
        got picked up, which is terminal rather than live, so including it would fill an
        emergency listing with dead calls and make --all fire pointless hangups at them.

        Our own `calls` table can't answer "what is live right now": a call whose webhook
        never arrived sits at status="in_progress" forever (the gap POST /api/calls/sync
        exists to close), so an emergency stop has to ask the platform, not the database.
        """
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{BASE_URL}/v2/list-calls",
                headers=self.headers,
                json={
                    # A bare array, NOT the {op, type, value} filter object the bundled
                    # retell SDK's call_list_params types describe — the live REST API
                    # rejects that shape with "call_status must be array". The SDK's
                    # generated types are ahead of the deployed API here; verified against
                    # the real endpoint, so don't "fix" this to match the SDK.
                    "filter_criteria": {"call_status": ["ongoing"]},
                    "limit": limit,
                },
            )
            resp.raise_for_status()
            body = resp.json()
        # v2/list-calls returns a bare array today; the SDK models a paginated
        # {items: [...]} shape. Accept either so a Retell-side pagination rollout
        # doesn't silently turn "kill everything live" into a no-op.
        if isinstance(body, dict):
            return list(body.get("items") or [])
        return list(body)

    async def list_platform_agents(self, limit: int = 100) -> list[dict[str, Any]]:
        """Every agent on the Retell account, including ones created by hand in their
        dashboard that this backend has never provisioned (ADR-012).

        Fetched live on each request rather than mirrored into our database: an agent
        renamed, re-voiced or deleted in Retell's dashboard must not still be offered by
        our dial picker, and there is no webhook telling us when that happens.

        Two normalizations worth knowing about:
          - `list-agents` returns one entry *per agent version*, so an agent edited five
            times appears five times. We keep the highest `version` per agent_id —
            that's the one Retell dials when `override_agent_id` names it without a
            version, so showing any other would misrepresent what the call will do.
          - `response_engine` is flattened to a bare `engine` string ("retell-llm",
            "custom-llm", "conversation-flow"). It's surfaced because it's the one field
            that tells an operator whether the agent runs on Retell's own brain or points
            back at a websocket — and an agent pointing at *someone else's* websocket is
            the case where "just dial it" does something we can't explain.
        """
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{BASE_URL}/list-agents", headers=self.headers, params={"limit": limit}
            )
            resp.raise_for_status()
            body = resp.json()

        # Bare array today; accept a paginated {items: [...]} too, same defensive shape as
        # list_live_calls — a Retell-side pagination rollout would otherwise silently
        # empty the picker.
        raw = list(body.get("items") or []) if isinstance(body, dict) else list(body)

        latest: dict[str, dict[str, Any]] = {}
        for item in raw:
            external_id = item.get("agent_id")
            if not external_id:
                continue
            previous = latest.get(external_id)
            if previous is not None and (item.get("version") or 0) <= (
                previous.get("version") or 0
            ):
                continue
            latest[external_id] = item

        return [
            {
                "external_id": item["agent_id"],
                # Retell allows an unnamed agent; the id is a poor label but beats a blank
                # row the operator can't tell apart from the next one.
                "name": item.get("agent_name") or item["agent_id"],
                "voice_id": item.get("voice_id"),
                "engine": (item.get("response_engine") or {}).get("type"),
                "version": item.get("version"),
                "last_modified_ms": item.get("last_modification_timestamp"),
            }
            for item in latest.values()
        ]

    async def get_agent_dynamic_variables(self, agent_external_id: str) -> list[str]:
        """The `{{placeholder}}` names this agent's prompt declares, sorted.

        These are the personalization slots for a platform-native agent (ADR-012): the
        prompt lives in Retell's dashboard and we can't rewrite it, but we CAN fill its
        placeholders per call via create_outbound_call(dynamic_variables=...).

        There is no API that reports them — Retell's own dashboard derives the list by
        scanning the prompt for `{{...}}`, and so do we (verified by probing a real agent:
        the four names the dashboard offered are exactly the four this regex finds). That
        makes this a best-effort read of someone else's template, which is why a missing
        or unreadable prompt returns [] rather than raising: not knowing the placeholders
        must not block a dial that may not need any.
        """
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{BASE_URL}/get-agent/{agent_external_id}", headers=self.headers
            )
            resp.raise_for_status()
            agent = resp.json()

            engine = agent.get("response_engine") or {}
            llm_id = engine.get("llm_id")
            if not llm_id:
                # custom-llm agents keep their prompt on whatever server answers the
                # websocket, and conversation-flow agents spread it across nodes — in
                # neither case is there a single prompt string here to scan.
                logger.info(
                    "get_agent_dynamic_variables: no retell-llm prompt to scan",
                    extra={"agent_external_id": agent_external_id, "engine": engine.get("type")},
                )
                return []

            llm_resp = await client.get(f"{BASE_URL}/get-retell-llm/{llm_id}", headers=self.headers)
            llm_resp.raise_for_status()
            llm = llm_resp.json()

        # begin_message is scanned too — an opener saying "Hi {{contact_name}}" is
        # precisely where an unfilled placeholder gets read aloud first.
        text = " ".join(
            part for part in (llm.get("general_prompt"), llm.get("begin_message")) if part
        )
        return sorted(set(_DYNAMIC_VARIABLE_RE.findall(text)))

    async def create_outbound_call(
        self,
        from_number: str,
        to_number: str,
        agent_external_id: str,
        dynamic_variables: dict[str, str] | None = None,
    ) -> str:
        """Place the call. `dynamic_variables` fills the agent prompt's `{{placeholders}}`
        for this call only (see get_agent_dynamic_variables) — Retell's per-call
        personalization channel for agents whose prompt we don't own.

        Omitted entirely when empty rather than sent as `{}`: the local-agent paths never
        use this, and an empty object is a needless difference in their request bodies.
        """
        body: dict[str, Any] = {
            "from_number": from_number,
            "to_number": to_number,
            "override_agent_id": agent_external_id,
        }
        if dynamic_variables:
            body["retell_llm_dynamic_variables"] = dynamic_variables

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{BASE_URL}/v2/create-phone-call", headers=self.headers, json=body
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
                retell_verify(body=raw_body, api_key=settings.retell_api_key, signature=signature)
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
