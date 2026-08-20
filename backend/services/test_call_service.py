"""Outbound "test call" — dial the operator's own phone so they can hear an
agent's live behavior.

Two provisioning paths, chosen by `agent.use_custom_llm`:

- **Hosted LLM (default, `use_custom_llm=False`)** — Retell's built-in LLM
  (response_engine "retell-llm") answers. No tunnel/WS server required. DeepSeek +
  server-side tools are NOT exercised — see ADR-003 for the real call-time brain,
  which this path intentionally bypasses for a quick, low-friction way to audition
  a script.
- **Custom LLM (`use_custom_llm=True`)** — Retell relays the conversation to OUR
  websocket (backend/api/retell_ws.py), which answers via DeepSeek + server-side
  tools (ADR-003, the real target architecture). Requires PUBLIC_BASE_URL (a public
  tunnel) to be set AND reachable — see tunnel_check.check_public_url_reachable,
  called before dialing so a dead tunnel fails fast instead of spending a real call
  on dead air.

A third path, `place_platform_agent_call`, sits alongside both: it dials an agent that
already exists on the platform (built in Retell's own dashboard) and provisions nothing
at all. See ADR-012 — the split is "do we own this agent's configuration", and the two
functions above answer yes while that one answers no.

ADR-002: all Retell HTTP stays behind the adapter; this service only orchestrates.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.models.agent import Agent
from backend.services import agent_service, call_service, public_url, tunnel_check
from backend.services.retell_adapter import RetellAdapter
from backend.services.voice_platform import get_adapter

settings = get_settings()

# Sentinel for "this key is absent from voice_config," distinct from "present and None" —
# see its use resolving ambientSound below, where None is itself a meaningful override
# value ("this campaign is explicitly silent"), not just an unset/falsy placeholder.
_NOT_SET = object()


class TestCallError(Exception):
    """Raised for operator-actionable failures (missing from-number, etc)."""


async def place_test_call(
    db: AsyncSession,
    agent_id: uuid.UUID,
    tenant_id: uuid.UUID,
    to_number: str,
    system_prompt_override: str | None = None,
    lead_id: uuid.UUID | None = None,
) -> dict:
    """Place an outbound call for `agent`.

    `system_prompt_override` lets a caller (e.g. prospect_service's per-company call)
    push a *personalized* variant (base script + [COMPANY BRIEF]) for just this call,
    without overwriting the agent's base `system_prompt` in the database — the campaign
    script stays the source of truth; personalization is call-time only. Supported on both
    engines, by different routes: the hosted path pushes it to Retell's LLM at
    provisioning time, while the custom-LLM path stores it on the Call row for
    backend/api/retell_ws.py to pick up (see Call.system_prompt_override).

    `lead_id` tags the resulting Call row so call_service's terminal-state writer can
    hand off to lead_service.evaluate_call_outcome (ADR-011) — None for every other
    caller (plain test calls, prospect calls).

    tenant_id is required: this endpoint spends real telephony money on the caller's
    Retell/Twilio account, so it must never dial on behalf of an agent the caller
    doesn't own.
    """
    agent = await agent_service.get_agent(db, agent_id, tenant_id)
    if not agent:
        raise TestCallError("Agent not found")

    if agent.platform != "retell":
        raise TestCallError(
            f"Test calls currently support Retell agents only (this agent is '{agent.platform}')"
        )

    if not settings.retell_from_number:
        raise TestCallError(
            "RETELL_FROM_NUMBER is not set. Buy a number in the Retell dashboard "
            "(Phone Numbers -> Buy a number), then set RETELL_FROM_NUMBER in .env and "
            "restart the API. To dial from an existing Twilio number instead, see "
            "phase2.md — that path needs a Twilio Elastic SIP Trunk first."
        )

    adapter = RetellAdapter()

    if agent.use_custom_llm:
        agent_external_id = await _provision_custom_llm_agent(db, adapter, agent)
    else:
        prompt = system_prompt_override or agent.system_prompt
        agent_external_id = await _provision_hosted_llm_agent(db, adapter, agent, prompt)

    call_id = await adapter.create_outbound_call(
        from_number=settings.retell_from_number,
        to_number=to_number,
        agent_external_id=agent_external_id,
    )

    # Create the Call row now — we have agent_id/tenant_id here, which webhook
    # events alone never carry. See call_service module docstring.
    #
    # The override is persisted only on the custom-LLM path: the hosted path already
    # pushed it to Retell during provisioning, and storing it here too would imply the
    # websocket should honor it for an agent whose calls never reach the websocket.
    await call_service.create_outbound_call_record(
        db,
        agent.tenant_id,
        agent.id,
        call_id,
        to_number,
        lead_id=lead_id,
        system_prompt_override=system_prompt_override if agent.use_custom_llm else None,
    )

    return {
        "call_id": call_id,
        "from_number": settings.retell_from_number,
        "status": "dialing",
    }


async def list_platform_agents(platform: str = "retell") -> list[dict]:
    """The voice platform's own agent roster (ADR-012) — read-only, live, unprovisioned.

    Deliberately takes no db/tenant: there is nothing tenant-scoped to read. The account
    behind RETELL_API_KEY is currently shared by every tenant, so this returns the same
    list to all of them — see ADR-012 for why that's a known gap rather than a design.
    """
    adapter = get_adapter(platform)
    try:
        return await adapter.list_platform_agents()
    except NotImplementedError as exc:
        raise TestCallError(f"'{platform}' does not expose an agent list") from exc


async def place_platform_agent_call(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    external_agent_id: str,
    to_number: str,
    platform: str = "retell",
) -> dict:
    """Dial using an agent that already exists on the voice platform (ADR-012).

    The whole point is what this function *doesn't* do: no provisioning, no prompt push,
    no webhook_url stamping, no tunnel preflight, no Custom LLM websocket. The agent was
    configured in the platform's dashboard and answers with whatever brain, voice and
    prompt it was given there — we contribute the from-number and the dial, nothing else.
    Contrast place_test_call above, which owns the agent it calls with.

    A Call row is still written, so external calls appear in the same history, analytics
    and reconcile paths as local ones. Two consequences follow from us not owning the
    agent, and both are real:
      - Lifecycle webhooks only arrive if the operator set our /webhooks/retell URL on
        that agent in the dashboard. Without it the row sits in_progress until someone
        runs POST /api/calls/sync, which reconciles it from the platform regardless
        (ADR-007) — that path needs only external_id, not an agent.
      - There is no system_prompt_override: the platform's agent holds the script, and
        nothing here can personalize a single call.
    """
    if not settings.retell_from_number:
        raise TestCallError(
            "RETELL_FROM_NUMBER is not set. Buy a number in the Retell dashboard "
            "(Phone Numbers -> Buy a number), then set RETELL_FROM_NUMBER in .env and "
            "restart the API."
        )

    adapter = get_adapter(platform)

    # Confirm the id is really on the account before spending a dial on it. A typo'd or
    # deleted agent otherwise surfaces as an opaque Retell 4xx, and — worse — a raw id
    # accepted unchecked from the client is the one place this endpoint could be pointed
    # at an agent outside the operator's own account.
    roster = await adapter.list_platform_agents()
    match = next((a for a in roster if a["external_id"] == external_agent_id), None)
    if not match:
        raise TestCallError(
            f"No agent '{external_agent_id}' on the connected {platform} account. "
            "It may have been deleted, or belong to a different account."
        )

    call_id = await adapter.create_outbound_call(
        from_number=settings.retell_from_number,
        to_number=to_number,
        agent_external_id=external_agent_id,
    )

    await call_service.create_outbound_call_record(
        db,
        tenant_id,
        None,
        call_id,
        to_number,
        external_agent_id=external_agent_id,
    )

    return {
        "call_id": call_id,
        "from_number": settings.retell_from_number,
        "status": "dialing",
        "agent_name": match["name"],
    }


async def _webhook_url() -> str | None:
    """Where Retell should POST call_started/call_ended/call_analyzed for agents we
    provision. None when there's no public URL — the hosted-LLM path is meant to work
    with no tunnel at all, so this stays optional rather than a hard requirement.

    The cost of it being None: no call lifecycle events arrive, so calls sit at
    status="in_progress" until someone runs POST /api/calls/sync. That reconcile path
    exists precisely to cover this case.

    Resolved via public_url rather than read off settings directly, so PUBLIC_BASE_URL
    ="auto" picks up the live quick-tunnel hostname. A discovery failure is treated the
    same as "no tunnel" here (rather than raised) to preserve exactly that: the hosted
    path must keep working without one.
    """
    try:
        base = await public_url.get_public_base_url(settings.public_base_url)
    except public_url.PublicUrlUnavailable:
        return None
    if not base:
        return None
    return f"{base}/webhooks/retell"


async def _provision_hosted_llm_agent(
    db: AsyncSession, adapter: RetellAdapter, agent: Agent, prompt: str
) -> str:
    """Retell's own hosted LLM. Caches {llm_id, agent_id, webhook_url} under
    voice_config["retell"] so a subsequent test call only needs a prompt update, not a
    recreate.

    Keyed on webhook_url as well as agent_id: a Retell agent's webhook URL is fixed at
    creation time, so an agent provisioned before PUBLIC_BASE_URL was set (or under a
    since-restarted tunnel) would otherwise keep pointing at a dead/absent webhook
    forever and its calls would never leave in_progress. Detecting the mismatch and
    recreating mirrors what _provision_custom_llm_agent does for ws_url.
    """
    retell_ids: dict = dict((agent.voice_config or {}).get("retell") or {})
    webhook_url = await _webhook_url()

    if retell_ids.get("llm_id"):
        await adapter.update_llm(retell_ids["llm_id"], prompt)
    else:
        retell_ids["llm_id"] = await adapter.create_llm(prompt)

    if not retell_ids.get("agent_id") or retell_ids.get("webhook_url") != webhook_url:
        voice_id = (agent.voice_config or {}).get("voiceId") or settings.retell_default_voice_id
        retell_ids["agent_id"] = await adapter.create_agent_with_llm(
            name=agent.name,
            llm_id=retell_ids["llm_id"],
            voice_id=voice_id,
            webhook_url=webhook_url,
        )
        retell_ids["webhook_url"] = webhook_url

    agent.voice_config = {**(agent.voice_config or {}), "retell": retell_ids}
    await db.commit()
    await db.refresh(agent)
    return retell_ids["agent_id"]


async def _provision_custom_llm_agent(
    db: AsyncSession,
    adapter: RetellAdapter,
    agent: Agent,
) -> str:
    """OUR Custom LLM WebSocket (backend/api/retell_ws.py) answers instead of Retell's
    hosted LLM — DeepSeek + server-side tools, ADR-003's actual target.

    Unlike the hosted path, no prompt is pushed to Retell at provisioning time: the WS
    handler reads the prompt fresh from the DB per call. A call-time
    system_prompt_override therefore does NOT belong here — it rides on the Call row
    instead (Call.system_prompt_override, written by place_test_call below), which is what
    retell_ws.py already looks up by external_id. That's also why the Retell agent stays
    shareable across personalized and non-personalized calls: nothing prospect-specific is
    baked into the provisioned agent, so no per-prospect re-provisioning is needed.

    Caches {agent_id, ws_url, webhook_url, begin_message_delay_ms, voice_id,
    interruption_sensitivity} under voice_config["retell_custom"], keyed on every one of
    them: a tunnel restart (which changes PUBLIC_BASE_URL) is detected and re-provisions
    instead of silently pointing Retell at a dead websocket, and likewise any
    creation-time agent setting that changed must force a new agent rather than quietly
    reusing one still carrying the old value.
    """
    try:
        base_url = await public_url.get_public_base_url(settings.public_base_url)
    except public_url.PublicUrlUnavailable as exc:
        raise TestCallError(str(exc)) from exc

    if not base_url:
        raise TestCallError(
            "PUBLIC_BASE_URL is not set. use_custom_llm requires a public tunnel so Retell "
            "can reach our websocket — start one (docker compose --profile tunnel up -d) "
            "and set PUBLIC_BASE_URL to its https URL in .env, or to 'auto' to have the "
            "quick tunnel's current URL discovered automatically."
        )

    # Being *set* isn't being *reachable*: a quick tunnel's hostname can stop resolving,
    # or the tunnel can die while `docker compose ps` still reports it as Up. Without this
    # check we'd provision Retell against a dead websocket, return 200 "dialing", and the
    # operator would spend a real, billed call on dead air with nothing in our logs to
    # explain why.
    unreachable_reason = await tunnel_check.check_public_url_reachable(base_url)
    if unreachable_reason and public_url.is_auto(settings.public_base_url):
        # Under "auto" an unreachable URL usually just means the tunnel restarted and
        # minted a new hostname while we were holding the old one. Re-ask cloudflared
        # once and retry before spending the operator's time on an error — this is the
        # whole point of "auto": a tunnel restart should be a non-event, not a failed
        # call plus a manual .env edit.
        try:
            base_url = await public_url.get_public_base_url(
                settings.public_base_url, force_refresh=True
            )
        except public_url.PublicUrlUnavailable as exc:
            raise TestCallError(str(exc)) from exc
        unreachable_reason = await tunnel_check.check_public_url_reachable(base_url)

    if unreachable_reason:
        raise TestCallError(
            f"PUBLIC_BASE_URL ({base_url}) is not reachable: "
            f"{unreachable_reason}. Retell dials our websocket from the public internet, "
            "so this call would be dead air. Note a dead tunnel still shows as 'Up' in "
            "`docker compose ps` — check `docker compose logs tunnel` for the current "
            "URL, or run `uv run python scripts/check_custom_llm.py` for a full diagnosis."
        )

    ws_base = base_url.replace("https://", "wss://").replace("http://", "ws://")
    ws_url = f"{ws_base}/llm-websocket"

    cached: dict = dict((agent.voice_config or {}).get("retell_custom") or {})
    webhook_url = await _webhook_url()

    # In the cache key for the same reason webhook_url is: it's fixed on the Retell agent
    # at creation, so a changed value has to force a re-provision or the setting would
    # silently never reach a previously-provisioned agent.
    begin_message_delay_ms = settings.greeting_delay_ms
    voice_id = (agent.voice_config or {}).get("voiceId") or settings.retell_default_voice_id
    interruption_sensitivity = settings.retell_interruption_sensitivity
    responsiveness = settings.retell_responsiveness
    # Per-agent override, resolved via a sentinel rather than `.get(..., settings.x)`:
    # None is a MEANINGFUL value here ("this campaign is explicitly silent," set from the
    # dashboard's Ambient sound picker), and `dict.get`'s default only fires when the key
    # is missing entirely, not when it's present-but-None — the same reason `or` doesn't
    # work for voice_id can't be reused here, since voice_id has no valid falsy override.
    ambient_sound = (agent.voice_config or {}).get("ambientSound", _NOT_SET)
    if ambient_sound is _NOT_SET:
        ambient_sound = settings.retell_ambient_sound
    expressive_mode = settings.retell_expressive_mode
    expressive_emotion_tags = settings.retell_expressive_emotion_tags

    # Every creation-time setting joins the key for the same reason: each is fixed on the
    # Retell agent at creation, so without it here a changed value would hit the cache,
    # reuse the old agent, and silently never take effect — which is exactly how call
    # fae0d38c ran on 11labs-Adrian at Retell's default sensitivity while the dashboard
    # showed a hand-edited agent nothing in this code path uses.
    if (
        cached.get("agent_id")
        and cached.get("ws_url") == ws_url
        and cached.get("webhook_url") == webhook_url
        and cached.get("begin_message_delay_ms") == begin_message_delay_ms
        and cached.get("voice_id") == voice_id
        and cached.get("interruption_sensitivity") == interruption_sensitivity
        and cached.get("responsiveness") == responsiveness
        and cached.get("ambient_sound") == ambient_sound
        and cached.get("expressive_mode") == expressive_mode
        and cached.get("expressive_emotion_tags") == expressive_emotion_tags
    ):
        return cached["agent_id"]

    agent_external_id = await adapter.create_agent_with_custom_llm(
        name=agent.name,
        llm_websocket_url=ws_url,
        voice_id=voice_id,
        webhook_url=webhook_url,
        begin_message_delay_ms=begin_message_delay_ms,
        interruption_sensitivity=interruption_sensitivity,
        responsiveness=responsiveness,
        ambient_sound=ambient_sound,
        expressive_mode=expressive_mode,
        expressive_emotion_tags=expressive_emotion_tags,
    )

    agent.voice_config = {
        **(agent.voice_config or {}),
        "retell_custom": {
            "agent_id": agent_external_id,
            "ws_url": ws_url,
            "webhook_url": webhook_url,
            "begin_message_delay_ms": begin_message_delay_ms,
            "voice_id": voice_id,
            "interruption_sensitivity": interruption_sensitivity,
            "responsiveness": responsiveness,
            "ambient_sound": ambient_sound,
            "expressive_mode": expressive_mode,
            "expressive_emotion_tags": expressive_emotion_tags,
        },
    }
    await db.commit()
    await db.refresh(agent)
    return agent_external_id
