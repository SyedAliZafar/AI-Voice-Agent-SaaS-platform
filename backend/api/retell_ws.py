"""Retell Custom LLM WebSocket — Retell dials in here during a live call and relays
transcript turns; we answer using the agent's configured model (ADR-008) + server-side
tools (ADR-003), replacing Retell's own hosted LLM for agents with
Agent.use_custom_llm=True. Also writes the turn-by-turn transcript as the call
progresses (see _persist_and_publish_turn) — previously only the post-call webhook
payload ever populated it.

Protocol: docs.retellai.com/api-references/llm-websocket. Retell appends the call's own
call_id to whatever base URL we registered via
RetellAdapter.create_agent_with_custom_llm's llm_websocket_url — see
backend/services/test_call_service.py's _provision_custom_llm_agent — so this route's
{call_id} path param is filled in by Retell itself, not something we template.

Tenant/agent resolution: Retell's frames carry only call_id, no auth header (see
backend/api/deps.py's docstring on why HTTP auth can't apply here). We resolve
tenant_id/agent_id by looking the Call row up by external_id — the same chain
call_service already uses for webhook events — which only works for calls this backend
originated (outbound-only today, per call_service's module docstring).

Streaming (ADR-009 — see CONTEXT.md): response_required/reminder_required turns run on
a cancellable asyncio.Task via llm_service.stream_agent_response, sending one
{"content": chunk, "content_complete": False} frame per delta so the caller hears
partial audio instead of dead air. If a new response_required with a different
response_id arrives while a turn is still generating (a barge-in), the in-flight task is
cancelled rather than left to finish — but cancellation only ever interrupts *speech*: a
tool call already dispatched (e.g. book_appointment's Cal.com POST) is shielded so it
still completes and gets recorded, never abandoned mid-flight with an unknown outcome.
settings.llm_streaming_enabled is the kill switch — False restores the original
single-frame blocking behavior via llm_service.get_agent_response, unchanged since
before this file went streaming.

Who speaks first (ADR-010): Retell only sends response_required once the *other* party
has spoken, so the agent's opener is generated here off the one-time call_details frame
instead, as a begin message on response_id 0. See _BEGIN_MESSAGE_INSTRUCTION and
_call_already_in_progress.
"""

import asyncio
import contextlib
import json
import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.api import ws as call_ws
from backend.config import get_settings
from backend.database import AsyncSessionLocal
from backend.services import agent_service, call_service, llm_service

logger = logging.getLogger(__name__)

router = APIRouter()
settings = get_settings()

_ROLE_MAP = {"agent": "assistant", "user": "user"}

# --- Completed-tool-call ledger (ADR-009 §4c) ------------------------------------
#
# Only tools that make a real, non-idempotent side effect are tracked here — repeating
# a *read* (lookup_customer) after a barge-in is harmless and sometimes correct, so it's
# deliberately excluded; telling the model "do NOT repeat lookup_customer" would be
# actively wrong. Each tool's tuple is the small set of identifying arguments worth
# showing the model, not the raw input dict (keeps an LLM-authored blob out of the
# prompt) — and the CallEvent(event_type="tool_call") rows written by _write_tool_event
# keep the complete, untruncated arguments/result regardless of what's rendered here.
_LEDGER_ARG_KEYS: dict[str, tuple[str, ...]] = {
    "book_appointment": ("start_time", "attendee_email"),
    "create_lead": ("email",),
    "send_sms": ("to_number", "message"),
    # cancel/reschedule identify WHICH booking they act on, not a date/email like
    # book_appointment — the booking_uid itself is the identifying argument
    # (outliers.md §5).
    "cancel_appointment": ("booking_uid",),
    "reschedule_appointment": ("booking_uid",),
    # Same class of bug outliers.md §1 documented for book_appointment: this is a
    # real (if lightweight) side-effecting booking capture, not a read, so a repeat
    # request must be caught too. No start_time/attendee_email field exists on this
    # tool's schema — phone + preferred_time is the closest analogous "who" + "when"
    # identifying pair.
    "book_discovery_call": ("phone", "preferred_time"),
}
_LEDGER_RESULT_ID_KEYS: dict[str, str] = {
    "book_appointment": "confirmation_id",
    "create_lead": "contact_id",
    "send_sms": "message_id",
    "reschedule_appointment": "confirmation_id",
    # cancel_appointment has no separate id worth displaying — its own target
    # booking_uid (already in `args` above) is the only reference that matters.
}
# Additional result fields worth carrying in a ledger entry beyond the single
# display-oriented result_id above. Currently only booking_uid: cancel/reschedule need
# Cal.com's string uid to act on a booking, never the numeric id result_id stores —
# without this, the model has no way to reference "the appointment I just booked" from
# the ledger note it already reads every turn (outliers.md §5).
_LEDGER_EXTRA_RESULT_KEYS: dict[str, tuple[str, ...]] = {
    "book_appointment": ("booking_uid",),
    "reschedule_appointment": ("booking_uid",),
}
_LEDGER_MAX_ARG_LEN = 40
_LEDGER_MAX_ENTRIES = 10


def _ledger_args_key(tool: str, arguments: dict[str, Any]) -> dict[str, str] | None:
    """The identifying-argument allowlist, truncated and stringified, shared by ledger
    entry construction (_ledger_entry) and duplicate matching (_find_duplicate_ledger_entry)
    — both MUST normalize a tool call's arguments the same way, or a freshly-requested
    call could fail to match an already-completed one it's actually identical to. Returns
    None for a tool the ledger doesn't track (see the comment above _LEDGER_ARG_KEYS)."""
    arg_keys = _LEDGER_ARG_KEYS.get(tool)
    if arg_keys is None:
        return None
    return {k: str(arguments.get(k, ""))[:_LEDGER_MAX_ARG_LEN] for k in arg_keys}


def _ledger_entry(
    tool: str, arguments: dict[str, Any], result: dict[str, Any]
) -> dict[str, Any] | None:
    """Builds one ledger entry for a completed tool call, or None if `tool` isn't one
    the ledger tracks (see the module-level comment above _LEDGER_ARG_KEYS), or if the
    result is an unconfirmed outcome (backend.tools.base.uncertain_result — a timeout
    that may or may not have actually happened server-side, outliers.md §5). An
    unconfirmed dispatch must not be recorded as completed: the ledger's whole purpose is
    telling the model "this is already done," which isn't true here, and a caller
    retrying it must not be blocked as a duplicate of something we never confirmed."""
    if result.get("status") == "uncertain":
        return None
    args = _ledger_args_key(tool, arguments)
    if args is None:
        return None
    result_id = result.get(_LEDGER_RESULT_ID_KEYS.get(tool, ""), "")
    extras = {
        k: str(result.get(k, ""))[:_LEDGER_MAX_ARG_LEN]
        for k in _LEDGER_EXTRA_RESULT_KEYS.get(tool, ())
    }
    return {
        "tool": tool,
        "args": args,
        "result_id": str(result_id)[:_LEDGER_MAX_ARG_LEN],
        "extras": extras,
    }


def _find_duplicate_ledger_entry(
    tool: str, arguments: dict[str, Any], completed_tool_calls: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Matches a fresh tool-call request against the connection's completed-tool-call
    ledger, using the exact same key _ledger_entry stored it under (via the shared
    _ledger_args_key) so normalization can't drift between the two sides of the
    comparison. This is the server-enforced half of ADR-009 §4c: a real double-booking
    on 2026-08-05 (outliers.md §1) showed the ledger's system-prompt note alone doesn't
    reliably stop a model from re-attempting something it already completed — this
    check runs in code, before dispatch, so it doesn't depend on the model complying.
    """
    args = _ledger_args_key(tool, arguments)
    if args is None:
        return None
    for entry in completed_tool_calls:
        if entry["tool"] == tool and entry["args"] == args:
            return entry
    return None


def _duplicate_tool_result(tool: str, entry: dict[str, Any]) -> dict[str, Any]:
    """The synthetic tool result fed back to the LLM in place of actually dispatching a
    repeat request — becomes the content of a {"role": "tool", ...} message, exactly
    like a real handler's return value would.

    Deliberately gives the model a positive action, not just a prohibition: the real
    call on 2026-08-05 (outliers.md §1) showed the model read an ambiguous caller
    follow-up ("four PM?") as a fresh instruction rather than a callback to a booking it
    had just made, immediately after being told (only in the system prompt, only in the
    negative) not to repeat it. "instruction" here tells the model what to SAY, at the
    exact moment — inside the tool result it's about to reason over — that it needs it,
    rather than relying on it remembering a system message from earlier in the prompt.

    Includes the matched entry's extras (currently only booking_uid) alongside
    result_id — a duplicate reschedule_appointment request matches on the OLD
    booking_uid it was asked to act on, but the model needs the NEW one (issued by the
    first, successful call) for anything further, not the stale value it just sent.
    """
    extras = entry.get("extras") or {}
    return {
        "already_completed": True,
        "reference": entry["result_id"],
        **extras,
        "instruction": (
            f"This {tool} request was already completed earlier in this call "
            f"(reference {entry['result_id']}"
            + (f", {', '.join(f'{k}={v}' for k, v in extras.items())}" if extras else "")
            + f"). Do not call {tool} again for it — tell the caller it's already done, "
            f"and confirm the details back to them."
        ),
    }


def _ledger_note(entries: list[dict[str, Any]]) -> str:
    """Renders the connection-scoped completed-tool-call ledger as one system message,
    injected ahead of conversation_history each turn (see _generate) — telling the model
    not to repeat a side effect that a barge-in's cancellation could otherwise cause it
    to re-attempt, since Retell's own transcript carries no record that the first call
    happened (ADR-009 §4c).

    Deduped on (tool, args) so a retry loop can't multiply entries, and capped at the
    _LEDGER_MAX_ENTRIES most recent — sized in the ADR to a bounded worst case of ~400
    tokens, well inside every catalog model's context window for the 1-3 side-effecting
    tool calls a real voice call realistically makes.
    """
    deduped: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    # Walk newest -> oldest keeping first-seen (i.e. most recent) occurrence of each
    # key, then reverse back to chronological order for rendering.
    for entry in reversed(entries):
        key = (entry["tool"], tuple(sorted(entry["args"].items())))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
    deduped.reverse()

    tail = deduped[-_LEDGER_MAX_ENTRIES:]
    omitted = len(deduped) - len(tail)
    lines = []
    for e in tail:
        extras = e.get("extras") or {}
        extras_suffix = f" [{', '.join(f'{k}={v}' for k, v in extras.items())}]" if extras else ""
        args_str = ", ".join(f"{k}={v}" for k, v in e["args"].items())
        lines.append(f"- {e['tool']}({args_str}) -> {e['result_id']}{extras_suffix}")
    if omitted > 0:
        lines.insert(0, f"...and {omitted} earlier actions")
    return "Already completed on this call — do NOT repeat these:\n" + "\n".join(lines)


_DATA_CAPTURE_BLOCK = (
    "[DATA_CAPTURE]\n"
    "When you capture a spoken name or email address:\n"
    "- Never repeat a guessed spelling back as a statement of fact. After the caller says "
    "an uncommon or ambiguous-sounding name, ask them to spell it, then read it back "
    "letter-by-letter using the NATO phonetic alphabet (e.g. 'S as in Sierra, H as in "
    "Hotel, A as in Alpha...') and wait for explicit yes/no confirmation before moving on "
    "or calling any tool with it.\n"
    "- If the caller corrects you, do not guess again — ask them to spell just the part "
    "you got wrong, or the whole word if that's easier for them, then re-confirm the same "
    "way.\n"
    "- When you say an email address out loud, always speak it as words, never symbols: "
    "say 'at' for '@' and 'dot' for '.' (e.g. 'syed dot ali at gmail dot com'). Never say "
    "'at the rate' or any other rendering of '@'.\n"
    "- Only pass a name or email to a tool call once the caller has confirmed it back to "
    "you as correct."
)

_SPEECH_BLOCK = (
    "[SPEECH]\n"
    "Everything you produce is spoken aloud by a text-to-speech engine, so it must be "
    "sayable as-is:\n"
    "- Never speak a placeholder. Prompt scripts contain fill-ins like [Name], "
    "[Your Name] or [insert service]; substitute the real value, or if you don't have "
    "one, rephrase the sentence without it. Saying the brackets out loud instantly "
    "exposes this as a script being read.\n"
    "- You do not have a personal first name unless your instructions give you one. "
    "Introduce yourself by who you're calling for (e.g. 'this is the assistant for "
    "Krucx') rather than inventing a human name that won't match anything the caller "
    "may later be told.\n"
    "- Never read stage directions, section headings, or notes-to-self aloud. If your "
    "instructions describe an action rather than words to say, perform it silently.\n"
    "- Output only the words to be spoken: no quotation marks wrapping your whole reply, "
    "no markdown, no asterisks, no bullet points, no emoji."
)


def _system_prompt_with_context(system_prompt: str, caller_number: str, time_zone: str) -> str:
    """Appends CONTEXT.md's documented "[CONTEXT] Current time / Caller number" block,
    plus a [DATA_CAPTURE] block, to the agent's own prompt.

    The model otherwise has no idea what day it is, and it shows: on a real test call on
    2026-08-05 the LLM invented "2024-08-06" and "2025-08-06" as start_time values for
    book_appointment, so every booking landed in the past. The prompt architecture in
    CONTEXT.md always specified this block — it just was never implemented on the
    custom-LLM path.

    [DATA_CAPTURE] exists for the same reason: a real call on 2026-08-12 showed the model
    guessing at a caller's name spelling repeatedly instead of confirming letter-by-letter,
    and reading "@" back in a way Retell's TTS rendered as "at the rate" instead of "at" —
    both silently wrong without an explicit instruction, since nothing in an agent's own
    persona prompt is expected to cover call-mechanics like this.

    [SPEECH] is the same category, found while verifying ADR-010's opener: the model read
    the literal placeholder "[Name]" out of the prompt's own script text and would have
    spoken "bracket Name" to a live prospect. The outbound templates in
    scripts/agent_templates/ are full of such fill-ins ([insert service] in the
    disinterest branch), and stage directions next to quoted script lines had already
    leaked once, so this is stated per-turn rather than only on the opening turn.

    Rebuilt per turn rather than once per connection so a long call can't drift across
    midnight, and stated in the agent's own calendar timezone so "tomorrow at 2pm" means
    what the caller means.
    """
    now = datetime.now(ZoneInfo(time_zone))
    return (
        f"{system_prompt}\n\n"
        f"[CONTEXT]\n"
        f"Current date and time: {now.strftime('%A, %d %B %Y, %H:%M')} ({time_zone}).\n"
        f"Today's date in ISO format is {now.date().isoformat()}. When the caller says a "
        f"relative day like 'tomorrow' or 'next Tuesday', resolve it against that date and "
        f"always pass a full ISO 8601 start_time in the CURRENT year.\n"
        f"Caller's phone number: {caller_number or 'unknown'}.\n\n"
        f"{_DATA_CAPTURE_BLOCK}\n\n"
        f"{_SPEECH_BLOCK}"
    )


_GREETING_SENTINEL = object()

_BEGIN_MESSAGE_INSTRUCTION = (
    "The call has just connected and the other party has not said anything yet. You are "
    "the one who placed this call, so you speak first — but this is only the FIRST of "
    "several short beats, not the whole pitch.\n"
    "Say two things and nothing else: who is calling, and a short check that now is an "
    "okay time. One or two sentences, under about 25 words total.\n"
    "Do NOT yet: explain what you do, deliver your hook, mention anything you looked up "
    "about them, list what you found, ask a qualifying question, or ask for two minutes "
    "of their time. Every one of those belongs to a later turn, after they have replied. "
    "Someone who just picked up the phone has no idea who you are yet — say who you are "
    "and let them answer."
)


def _call_already_in_progress(data: dict[str, Any]) -> bool:
    """Whether this call_details frame describes a call that has already been talking.

    The config frame sets auto_reconnect=True, so Retell can re-open this socket
    mid-call and replay call_details — speaking the opener again at that point would
    talk over a conversation already in progress and restart the pitch from the top.
    A call that hasn't started has no transcript yet, which is what distinguishes the
    real start from a reconnect. Both spellings are checked because Retell carries the
    plain-text transcript and the structured one under separate keys.
    """
    call = data.get("call") or {}
    return bool(call.get("transcript") or call.get("transcript_object"))


def _to_conversation_history(transcript: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Retell's transcript uses role "agent"/"user"; llm_service.get_agent_response
    expects OpenAI-style "assistant"/"user"."""
    return [
        {
            "role": _ROLE_MAP.get(turn.get("role", "user"), "user"),
            "content": turn.get("content", ""),
        }
        for turn in transcript
    ]


async def _persist_and_publish_turn(
    call_id: str,
    transcript_so_far: list[dict[str, Any]],
    agent_reply: str,
    llm_events: list[dict[str, Any]],
) -> None:
    """Write the turn-by-turn transcript as the call happens, and broadcast it to any
    dashboard clients watching (gives ws.py's previously-inert publish_call_event its
    first caller). Also persists this turn's llm_events (see llm_service.get_agent_response's
    llm_events param) as CallEvent(event_type="llm_timing") rows — the before/after
    baseline requested ahead of the streaming-architecture work.

    Called AFTER the response frame is sent — deliberate, keeps DB/Redis work off the
    turn-latency path phase0.md measured against a 1.5s budget. A short-lived session,
    per the module docstring's "sessions are opened fresh per connection". Any failure
    here is logged and swallowed: a Postgres hiccup or a down Redis must never take
    down a live phone call.

    Not called at all for a turn that was cancelled by a barge-in *before* its terminal
    frame was sent — deliberate, and self-healing for *speech*: record_turns rewrites
    Transcript.turns wholesale from transcript_so_far every turn, and Retell's next
    response_required carries its own transcript of what was actually spoken before the
    interruption, so nothing here needs to reconstruct a partial turn. This does NOT
    cover tool side effects — a cancelled turn's tool call is durably recorded regardless
    via _write_tool_event, which is not gated on this function ever running (ADR-009).

    Once the terminal frame HAS been sent, this call is itself shielded (see the call
    site in _generate) — a turn that's already fully spoken is done, and a same-instant
    barge-in or disconnect must not cancel writing it down.
    """
    try:
        turns = call_service.parse_retell_turns(transcript_so_far)
        turns.append({"role": "agent", "text": agent_reply})

        async with AsyncSessionLocal() as db:
            call = await call_service.get_call_by_external_id(db, call_id)
            if call:
                await call_service.record_turns(db, call, turns)
                await call_service.record_llm_events(db, call, llm_events)
                await db.commit()

        await call_ws.publish_call_event(
            call_id, {"type": "turn", "role": "agent", "text": agent_reply}
        )
    except Exception:
        logger.warning(
            "llm_websocket: failed to persist/publish turn",
            extra={"call_id": call_id},
            exc_info=True,
        )


@router.websocket("/llm-websocket/{call_id}")
async def llm_websocket(websocket: WebSocket, call_id: str) -> None:
    await websocket.accept()

    async with AsyncSessionLocal() as db:
        call = await call_service.get_call_by_external_id(db, call_id)
        if not call:
            logger.warning("llm_websocket: unknown call_id, closing", extra={"call_id": call_id})
            await websocket.close(code=1008)
            return

        # call.agent_id/tenant_id are real uuid.UUID at runtime; the type: ignore is for
        # a pre-existing annotation gap (Mapped[UUID] instead of Mapped[uuid.UUID]) that
        # spans models/call.py and models/agent.py, not something specific to this line.
        agent = await agent_service.get_agent(db, call.agent_id, call.tenant_id)  # type: ignore[arg-type]
        if not agent:
            logger.warning(
                "llm_websocket: call has no resolvable agent, closing",
                extra={"call_id": call_id, "agent_id": str(call.agent_id)},
            )
            await websocket.close(code=1008)
            return

        system_prompt = agent.system_prompt
        llm_model = agent.llm_model or None  # None -> llm_service.get_agent_response's default
        caller_context: dict[str, Any] = {
            "caller_number": call.caller_number,
            "tenant_id": str(call.tenant_id),
            "agent_id": str(call.agent_id),
        }
        # book_appointment/create_lead expect calendar_id/calendar_api_key/crm_api_key
        # in caller_context (see backend/tools/book_appointment.py,
        # backend/tools/create_lead.py) — those live per-agent in ToolConfig.config
        # (models/agent.py), keyed by tool_type. Flatten every configured tool's
        # config dict into caller_context so the tools stop hitting empty credentials.
        tool_configs = await agent_service.get_tool_configs(db, call.agent_id)  # type: ignore[arg-type]
        for tool_config in tool_configs:
            caller_context.update(tool_config.config)

    # Read once per connection (ADR-009) — a mid-call settings change must not produce
    # an inconsistent mix of framing within a single conversation.
    streaming_enabled = settings.llm_streaming_enabled

    # --- Per-connection state -----------------------------------------------------
    send_lock = asyncio.Lock()
    current_task: asyncio.Task | None = None
    current_response_id: Any = None
    # Tasks that must be allowed to finish even if the turn that spawned them is
    # cancelled: shielded tool-call execution (ADR-009 §4a), the fire-and-forget
    # CallEvent writes for llm_service's on_tool_event sink (§4b), and — once a turn's
    # terminal frame has actually been sent — that turn's _persist_and_publish_turn
    # call, which by then must survive a same-instant barge-in/disconnect just like a
    # tool call would. Drained in `finally` on disconnect.
    pending_tool_tasks: set[asyncio.Task] = set()
    # tool_call_id -> (tool_name, parsed_arguments), populated at "dispatched" and
    # consumed at "result" so the ledger entry can pair identifying args with the
    # result's id — see _on_tool_event.
    _dispatch_args: dict[str, tuple[str, dict[str, Any]]] = {}
    # Connection-scoped, not turn-scoped: a ledger entry from a cancelled turn must
    # survive that turn's cancelled task, since it's exactly the barge-in case this
    # ledger exists to cover (ADR-009 §4c).
    completed_tool_calls: list[dict[str, Any]] = []

    async def _send(payload: dict[str, Any]) -> None:
        async with send_lock:
            try:
                await websocket.send_json(payload)
            except (WebSocketDisconnect, RuntimeError):
                # Socket already closed (Retell hung up mid-generation) — nothing to
                # send to; the disconnect itself is handled by the receive loop.
                pass

    def _spawn_tracked(coro: Any) -> asyncio.Task:
        task = asyncio.create_task(coro)
        pending_tool_tasks.add(task)
        task.add_done_callback(pending_tool_tasks.discard)
        return task

    async def _write_tool_event(payload: dict[str, Any]) -> None:
        try:
            async with AsyncSessionLocal() as event_db:
                event_call = await call_service.get_call_by_external_id(event_db, call_id)
                if event_call:
                    await call_service.record_tool_event(event_db, event_call, payload)
        except Exception:
            logger.warning(
                "llm_websocket: failed to persist tool event",
                extra={"call_id": call_id, "tool": payload.get("tool")},
                exc_info=True,
            )

    def _on_tool_event(response_id: Any, event: dict[str, Any]) -> None:
        """llm_service's on_tool_event sink for this connection — called synchronously,
        never awaited, from inside the (possibly shielded) tool-execution task. Updates
        the ledger on a successful "result" and always schedules a durable, tracked,
        fire-and-forget CallEvent write (ADR-009 §4b) — never an inline await, which
        would put a DB round-trip in front of the tool call itself."""
        tool = event["tool"]
        tool_call_id = event["tool_call_id"]
        phase = event["phase"]

        if phase == "dispatched":
            try:
                parsed_args = json.loads(event.get("arguments") or "{}")
            except (TypeError, ValueError):
                parsed_args = {}
            _dispatch_args[tool_call_id] = (tool, parsed_args)
        elif phase == "result":
            _, parsed_args = _dispatch_args.pop(tool_call_id, (tool, {}))
            result = event.get("result")
            if isinstance(result, dict):
                entry = _ledger_entry(tool, parsed_args, result)
                if entry:
                    completed_tool_calls.append(entry)
        elif phase == "skipped_duplicate":
            # Never went through "dispatched" (see _check_duplicate below, called before
            # that phase fires) — nothing to clean up in _dispatch_args, and the ledger
            # already contains the entry that caused the skip. Explicit branch so this
            # isn't silently absorbed by the "error" fallback below.
            pass
        else:  # "error"
            _dispatch_args.pop(tool_call_id, None)

        _spawn_tracked(_write_tool_event({**event, "response_id": response_id}))

    def _check_duplicate(tool: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
        """Passed to llm_service as check_duplicate (ADR-009 §4c server-enforced half /
        phase4.md Session 8) — consulted before every tool dispatch, in code, so a
        repeat request for something already on the ledger never reaches the real
        handler regardless of what the model decides. See _find_duplicate_ledger_entry
        and _duplicate_tool_result for the matching/response logic itself."""
        entry = _find_duplicate_ledger_entry(tool, arguments, completed_tool_calls)
        if entry is None:
            return None
        return _duplicate_tool_result(tool, entry)

    async def _generate(data: dict[str, Any], *, greeting: bool = False) -> None:
        """Generate and speak one turn. `greeting` is the call-opening turn (ADR-010):
        no caller utterance to answer, just the agent's own opener, and tools are
        disabled for it — nothing can legitimately need booking or a lookup before the
        other party has said a single word.

        Nothing here waits before speaking: the pause that lets the person say "Hello?"
        first is Retell's begin_message_delay_ms, set at provisioning time. This socket
        opens during call *setup*, so a timer started here expires while the phone is
        still ringing — it looked like it worked and did nothing on a real call.
        """
        response_id = data.get("response_id")
        transcript_so_far = data.get("transcript", [])
        conversation_history = _to_conversation_history(transcript_so_far)
        if greeting:
            conversation_history.append(
                {"role": "system", "content": _BEGIN_MESSAGE_INSTRUCTION}
            )
        if completed_tool_calls:
            conversation_history.insert(
                0, {"role": "system", "content": _ledger_note(completed_tool_calls)}
            )
        turn_system_prompt = _system_prompt_with_context(
            system_prompt,
            caller_context.get("caller_number", ""),
            caller_context.get("calendar_timezone", "UTC"),
        )

        def sink(event: dict[str, Any]) -> None:
            _on_tool_event(response_id, event)

        llm_events: list[dict[str, Any]] = []
        spoken: list[str] = []
        text: str | None = None
        fallback_text: str | None = None

        try:
            if streaming_enabled:
                async for chunk in llm_service.stream_agent_response(
                    turn_system_prompt,
                    conversation_history,
                    caller_context,
                    model=llm_model,
                    tools_enabled=not greeting,
                    llm_events=llm_events,
                    on_tool_event=sink,
                    spawn_tracked=_spawn_tracked,
                    check_duplicate=_check_duplicate,
                ):
                    spoken.append(chunk)
                    await _send(
                        {
                            "response_type": "response",
                            "response_id": response_id,
                            "content": chunk,
                            "content_complete": False,
                            "end_call": False,
                        }
                    )
            else:
                text = await llm_service.get_agent_response(
                    turn_system_prompt,
                    conversation_history,
                    caller_context,
                    model=llm_model,
                    tools_enabled=not greeting,
                    llm_events=llm_events,
                    on_tool_event=sink,
                    spawn_tracked=_spawn_tracked,
                    check_duplicate=_check_duplicate,
                )
        except asyncio.CancelledError:
            # A barge-in (a new response_id arrived) — not an LLM failure. Must not be
            # caught by the broad except below, or an interrupted caller would hear an
            # apology instead of nothing. No terminal frame is sent for this response_id
            # and _persist_and_publish_turn never runs for this turn (see its docstring
            # for why that's fine for speech but NOT a free pass for tool side effects —
            # those are shielded separately, see llm_service._run_tool_calls_shielded).
            raise
        except llm_service.LLMConfigError:
            # CONTEXT.md's documented LLM-failure fallback — an unresolvable
            # model/missing key must not kill a live call.
            logger.exception(
                "llm_websocket: LLM config error, using fallback response",
                extra={"call_id": call_id, "model": llm_model},
            )
            fallback_text = "I'm having trouble, let me transfer you."
        except Exception:
            # Timeouts, rate limits, 5xxs etc. from the OpenAI-compatible SDK —
            # same fallback contract as LLMConfigError above: never let a
            # transient provider failure kill the live call/websocket.
            logger.exception(
                "llm_websocket: LLM call failed, using fallback response",
                extra={"call_id": call_id, "model": llm_model},
            )
            fallback_text = "I'm having some trouble, let me get someone to help you."

        # Exactly one terminal frame either way. If streaming already sent partial
        # frames and nothing failed, this is an empty "close out" increment; if it
        # failed after partial audio, this appends the apology to what was already
        # spoken. In blocking mode there were no partials, so this single frame carries
        # the whole reply — byte-for-byte the pre-streaming wire behavior.
        if fallback_text is not None:
            full_text = fallback_text
            terminal_content = fallback_text
        elif streaming_enabled:
            full_text = "".join(spoken)
            terminal_content = ""
        else:
            full_text = text or ""
            terminal_content = full_text

        await _send(
            {
                "response_type": "response",
                "response_id": response_id,
                "content": terminal_content,
                "content_complete": True,
                "end_call": False,
            }
        )
        # Shielded and tracked for the same reason tool execution is (ADR-009 §4a): the
        # terminal frame is already on the wire, so this turn is done from Retell's
        # perspective and may already be sending the next response_required — a
        # same-instant barge-in or disconnect must not cancel the transcript write for
        # a turn that already completed. Without this, `finally`'s
        # `current_task.cancel()` on disconnect could race this exact await and silently
        # drop the turn's persistence, which is what _persist_and_publish_turn's own
        # "not called at all for a cancelled turn" docstring assumes never happens once
        # the terminal frame has actually been sent.
        await asyncio.shield(
            _spawn_tracked(
                _persist_and_publish_turn(call_id, transcript_so_far, full_text, llm_events)
            )
        )

    # Required as the first message per Retell's protocol.
    await websocket.send_json(
        {
            "response_type": "config",
            "config": {
                "auto_reconnect": True,
                "call_details": True,
                "transcript_with_tool_calls": False,
            },
        }
    )

    try:
        while True:
            data = await websocket.receive_json()
            interaction_type = data.get("interaction_type")

            if interaction_type == "ping_pong":
                await _send({"response_type": "ping_pong", "timestamp": data.get("timestamp")})
            elif interaction_type == "call_details":
                # ADR-010: speak first. Retell only sends response_required *after* the
                # other party talks, so without this the agent sat silent until the
                # person it called said something — backwards for outbound cold calls,
                # where the agent is the one who dialed and owes the opener. Retell's
                # protocol reserves response_id 0 for exactly this begin message.
                if _call_already_in_progress(data):
                    continue
                # A sentinel, not 0: current_response_id is only ever compared against
                # incoming ids to tell "Retell resent this turn" from "genuine barge-in",
                # and an incoming 0 here is the latter — the person answered and spoke
                # during the opening pause. A sentinel can't collide, so their speech
                # always cancels the opener instead of being mistaken for a resend.
                current_response_id = _GREETING_SENTINEL
                current_task = asyncio.create_task(
                    _generate({"response_id": 0, "transcript": []}, greeting=True)
                )
            elif interaction_type in ("response_required", "reminder_required"):
                response_id = data.get("response_id")
                if current_task is not None and not current_task.done():
                    if response_id == current_response_id:
                        # Retell resending the same still-in-flight turn — let the
                        # original generation finish rather than restarting it.
                        continue
                    # A genuine barge-in: cancel the stale generation and wait for it to
                    # actually stop before starting the new one, so only one task is
                    # ever mid-send on this socket at a time.
                    current_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await current_task
                current_response_id = response_id
                current_task = asyncio.create_task(_generate(data))
            # update_only: no response required, nothing to do.
    except WebSocketDisconnect:
        pass
    finally:
        if current_task is not None and not current_task.done():
            current_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await current_task
        # Drain shielded tool tasks and their event-write tasks (ADR-009 §4a/§4b) so a
        # hangup mid-booking still lets the booking — and its CallEvent trace — finish.
        # Re-checks the set rather than a single gather: the "result" event task for a
        # tool call is only created *after* its handler returns, which can happen
        # during this very drain, so a one-shot snapshot would miss it.
        try:
            deadline = asyncio.get_running_loop().time() + 10.0
            while pending_tool_tasks:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    logger.warning(
                        "llm_websocket: tool-task drain timed out",
                        extra={"call_id": call_id, "pending": len(pending_tool_tasks)},
                    )
                    break
                await asyncio.wait(set(pending_tool_tasks), timeout=remaining)
        except Exception:
            logger.warning(
                "llm_websocket: error draining tool tasks",
                extra={"call_id": call_id},
                exc_info=True,
            )
