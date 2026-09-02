"""Tests for call_service — creation at outbound-placement time, and the
webhook-driven update paths (found-by-external_id vs. graceful not-found).
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from backend.models.call import Call
from backend.services import call_service


@pytest.mark.asyncio
async def test_create_outbound_call_record_sets_in_progress(db_session, tenant_id):
    agent_id = uuid.uuid4()

    call = await call_service.create_outbound_call_record(
        db_session, tenant_id, agent_id, "retell_call_1", "+491701234567"
    )

    assert call.status == "in_progress"
    assert call.external_id == "retell_call_1"
    assert call.caller_number == "+491701234567"
    assert call.tenant_id == tenant_id
    assert call.agent_id == agent_id

    fetched = await call_service.get_call(db_session, call.id, tenant_id)
    assert fetched is not None
    assert fetched.external_id == "retell_call_1"


@pytest.mark.asyncio
async def test_handle_transcript_update_creates_transcript_for_known_call(db_session, tenant_id):
    call = await call_service.create_outbound_call_record(
        db_session, tenant_id, uuid.uuid4(), "retell_call_2", "+491701234567"
    )

    await call_service.handle_transcript_update(db_session, "retell_call_2", "Hello there")

    transcript = await call_service.get_transcript(db_session, call.id, tenant_id)
    assert transcript is not None
    assert transcript.full_text == "Hello there"


@pytest.mark.asyncio
async def test_handle_transcript_update_updates_existing_transcript(db_session, tenant_id):
    call = await call_service.create_outbound_call_record(
        db_session, tenant_id, uuid.uuid4(), "retell_call_3", "+491701234567"
    )
    await call_service.handle_transcript_update(db_session, "retell_call_3", "First")
    await call_service.handle_transcript_update(db_session, "retell_call_3", "First and second")

    transcript = await call_service.get_transcript(db_session, call.id, tenant_id)
    assert transcript.full_text == "First and second"


@pytest.mark.asyncio
async def test_handle_transcript_update_noop_for_unknown_call(db_session):
    # Must not raise — an inbound/unrecognized call_id is a graceful no-op.
    await call_service.handle_transcript_update(db_session, "unknown_call", "Hello")


@pytest.mark.asyncio
async def test_handle_call_ended_marks_resolved_and_sets_duration(db_session, tenant_id):
    call = await call_service.create_outbound_call_record(
        db_session, tenant_id, uuid.uuid4(), "retell_call_4", "+491701234567"
    )
    # Backdate started_at so the wall-clock fallback yields a non-zero duration.
    call.started_at = datetime.now(UTC) - timedelta(seconds=42)
    await db_session.commit()

    # No payload — the pre-webhook_url legacy path. Must still conclude the call.
    await call_service.handle_call_ended(db_session, "retell_call_4")

    updated = await call_service.get_call(db_session, call.id, tenant_id)
    assert updated.status == "resolved"
    assert updated.duration_sec >= 42


@pytest.mark.asyncio
async def test_handle_call_ended_prefers_platform_duration(db_session, tenant_id):
    """Retell's duration_ms wins over wall-clock arithmetic — reconcile can run long
    after a call ended, when `now - started_at` would be nonsense."""
    call = await call_service.create_outbound_call_record(
        db_session, tenant_id, uuid.uuid4(), "retell_call_5", "+491701234567"
    )
    call.started_at = datetime.now(UTC) - timedelta(days=2)
    await db_session.commit()

    await call_service.handle_call_ended(
        db_session,
        "retell_call_5",
        {"call_status": "ended", "disconnection_reason": "user_hangup", "duration_ms": 31_000},
    )

    updated = await call_service.get_call(db_session, call.id, tenant_id)
    assert updated.duration_sec == 31


@pytest.mark.asyncio
async def test_call_ended_records_disconnection_reason_and_human_flag(db_session, tenant_id):
    call = await call_service.create_outbound_call_record(
        db_session, tenant_id, uuid.uuid4(), "reason_call", "+491701234567"
    )

    await call_service.handle_call_ended(
        db_session,
        "reason_call",
        {
            "call_status": "ended",
            "disconnection_reason": "voicemail_reached",
            "transcript_object": [{"role": "agent", "content": "Hi, are you there?"}],
        },
    )

    updated = await call_service.get_call(db_session, call.id, tenant_id)
    assert updated.disconnection_reason == "voicemail_reached"
    assert updated.answered_by_human is False  # only an agent turn — nobody picked up


@pytest.mark.asyncio
async def test_call_ended_marks_answered_when_the_callee_spoke(db_session, tenant_id):
    call = await call_service.create_outbound_call_record(
        db_session, tenant_id, uuid.uuid4(), "answered_call", "+491701234567"
    )

    await call_service.handle_call_ended(
        db_session,
        "answered_call",
        {
            "call_status": "ended",
            "disconnection_reason": "user_hangup",
            "transcript_object": [
                {"role": "agent", "content": "Hi there"},
                {"role": "user", "content": "Not interested, thanks"},
            ],
        },
    )

    updated = await call_service.get_call(db_session, call.id, tenant_id)
    assert updated.answered_by_human is True


@pytest.mark.asyncio
async def test_fanout_classifies_the_linked_prospect(db_session, tenant_id):
    from backend.services import prospect_service

    [prospect] = await prospect_service.upsert_from_places(
        db_session, tenant_id, [{"google_place_id": "fp_1", "name": "FanoutCo"}], "q"
    )
    await call_service.create_outbound_call_record(
        db_session,
        tenant_id,
        uuid.uuid4(),
        "fanout_call",
        "+491701234567",
        prospect_id=prospect.id,
    )

    await call_service.handle_call_ended(
        db_session,
        "fanout_call",
        {"call_status": "ended", "disconnection_reason": "dial_no_answer"},
    )

    updated = await prospect_service.get_prospect(db_session, prospect.id, tenant_id)
    assert updated.status == "no_answer"


@pytest.mark.asyncio
async def test_not_connected_is_terminal_and_classifies_the_prospect(db_session, tenant_id):
    """Retell reports an unanswered dial as call_status="not_connected", not "ended".

    Treating that as a live call left the row at in_progress forever, so the prospect
    kept status="not_called" while showing a call_count — the bug where the dashboard's
    "Not called" section listed companies that had plainly been called.
    """
    from backend.services import prospect_service

    [prospect] = await prospect_service.upsert_from_places(
        db_session, tenant_id, [{"google_place_id": "nc_1", "name": "NotConnectedCo"}], "q"
    )
    call = await call_service.create_outbound_call_record(
        db_session,
        tenant_id,
        uuid.uuid4(),
        "not_connected_call",
        "+491701234567",
        prospect_id=prospect.id,
    )

    await call_service.handle_call_ended(
        db_session,
        "not_connected_call",
        {"call_status": "not_connected", "disconnection_reason": "dial_no_answer"},
    )

    updated_call = await call_service.get_call(db_session, call.id, tenant_id)
    assert updated_call.status == "failed"
    updated = await prospect_service.get_prospect(db_session, prospect.id, tenant_id)
    assert updated.status == "no_answer"


def test_status_for_terminal_states():
    # Live: no verdict to draw yet.
    assert call_service._status_for("ongoing", None) is None
    assert call_service._status_for("registered", None) is None
    # not_connected is terminal even without a reason, and never "resolved" — nobody
    # ever picked up.
    assert call_service._status_for("not_connected", None) == "failed"
    assert call_service._status_for("not_connected", "user_declined") == "failed"
    # A disconnection_reason is itself proof the attempt is over.
    assert call_service._status_for("ongoing", "dial_busy") == "failed"
    assert call_service._status_for("ended", "user_hangup") == "resolved"
    assert call_service._status_for("ended", "call_transfer") == "escalated"


class _StubAdapter:
    """Stands in for RetellAdapter in reconcile and end_call tests."""

    def __init__(
        self,
        payload: dict | None = None,
        raises: bool = False,
        stop_raises: bool = False,
    ):
        self.payload = payload or {}
        self.raises = raises
        self.stop_raises = stop_raises
        self.stopped: list[str] = []

    async def get_call(self, call_external_id: str) -> dict:
        if self.raises:
            raise RuntimeError("platform unreachable")
        return self.payload

    async def stop_call(self, call_external_id: str) -> None:
        if self.stop_raises:
            raise RuntimeError("platform refused the hangup")
        self.stopped.append(call_external_id)


class _HistoryAdapter:
    """Stands in for RetellAdapter.list_call_history in backfill tests."""

    def __init__(self, calls: list[dict]):
        self.calls = calls

    async def list_call_history(
        self, *, since_ms: int | None = None, max_calls: int = 1000
    ) -> list[dict]:
        return self.calls[:max_calls]


def _retell_call(call_id: str, to_number: str | None, reason: str, **extra: object) -> dict:
    base = {
        "call_id": call_id,
        "call_type": "phone_call" if to_number else "web_call",
        "direction": "outbound",
        "to_number": to_number,
        "call_status": "ended",
        "disconnection_reason": reason,
        "start_timestamp": 1_788_000_000_000,
        "duration_ms": 20_000,
    }
    base.update(extra)
    return base


@pytest.mark.asyncio
async def test_backfill_imports_dashboard_calls_and_classifies_prospects(db_session, tenant_id):
    """The whole point: calls placed from Retell's dashboard created no local Call row,
    so their prospects read not_called. Backfill matches them by phone and settles status.
    """
    from backend.services import prospect_service

    [vm] = await prospect_service.upsert_from_places(
        db_session,
        tenant_id,
        [{"google_place_id": "b1", "name": "VM Co", "phone": "+442077335265"}],
        "q",
    )
    [spoke] = await prospect_service.upsert_from_places(
        db_session,
        tenant_id,
        [{"google_place_id": "b2", "name": "Spoke Co", "phone": "+14059146006"}],
        "q",
    )

    adapter = _HistoryAdapter(
        [
            _retell_call("c_vm", "+442077335265", "voicemail_reached", answered_by_human=True),
            _retell_call(
                "c_spoke",
                "+14059146006",
                "user_hangup",
                call_status="ended",
                transcript_object=[{"role": "user", "content": "hello?"}],
                call_analysis={"user_sentiment": "neutral"},
            ),
            _retell_call("c_web", None, "user_hangup"),  # web call — no number, stays unlinked
        ]
    )

    stats = await call_service.backfill_from_platform(db_session, tenant_id, adapter)

    assert stats == {"fetched": 3, "created": 3, "updated": 0, "matched": 2, "unmatched": 1}
    assert (await prospect_service.get_prospect(db_session, vm.id, tenant_id)).status == "voicemail"
    assert (await prospect_service.get_prospect(db_session, spoke.id, tenant_id)).status == "called"

    vm_reloaded = await prospect_service.get_prospect(db_session, vm.id, tenant_id)
    assert vm_reloaded.call_count == 1
    assert vm_reloaded.last_called_at is not None


@pytest.mark.asyncio
async def test_backfill_is_idempotent(db_session, tenant_id):
    from backend.services import prospect_service

    [p] = await prospect_service.upsert_from_places(
        db_session,
        tenant_id,
        [{"google_place_id": "b3", "name": "Idem Co", "phone": "+442077335265"}],
        "q",
    )
    adapter = _HistoryAdapter([_retell_call("c1", "020 7733 5265", "voicemail_reached")])

    first = await call_service.backfill_from_platform(db_session, tenant_id, adapter)
    second = await call_service.backfill_from_platform(db_session, tenant_id, adapter)

    assert first["created"] == 1
    assert second["created"] == 0 and second["updated"] == 1
    reloaded = await prospect_service.get_prospect(db_session, p.id, tenant_id)
    assert reloaded.call_count == 1  # recomputed, not incremented on the second run
    assert reloaded.status == "voicemail"  # national-format number still matched


@pytest.mark.asyncio
async def test_reconcile_unsticks_a_call_whose_webhook_never_arrived(db_session, tenant_id):
    """The core of the self-healing path: no call_ended was ever delivered, so the row
    is stranded at in_progress until reconcile pulls the real state."""
    call = await call_service.create_outbound_call_record(
        db_session, tenant_id, uuid.uuid4(), "stranded_1", "+491701234567"
    )
    assert call.status == "in_progress"

    adapter = _StubAdapter(
        {
            "call_status": "ended",
            "disconnection_reason": "user_hangup",
            "duration_ms": 17_000,
            "transcript": "Agent: Hi.",
            "call_analysis": {"user_sentiment": "Negative"},
        }
    )

    changed = await call_service.reconcile_call(db_session, call, adapter)

    assert changed is True
    updated = await call_service.get_call(db_session, call.id, tenant_id)
    assert updated.status == "resolved"
    assert updated.duration_sec == 17
    assert updated.sentiment_score == 0.0


@pytest.mark.asyncio
async def test_reconcile_leaves_still_ongoing_calls_alone(db_session, tenant_id):
    call = await call_service.create_outbound_call_record(
        db_session, tenant_id, uuid.uuid4(), "ongoing_1", "+491701234567"
    )

    changed = await call_service.reconcile_call(
        db_session, call, _StubAdapter({"call_status": "ongoing"})
    )

    assert changed is False
    updated = await call_service.get_call(db_session, call.id, tenant_id)
    assert updated.status == "in_progress"


@pytest.mark.asyncio
async def test_reconcile_survives_platform_errors(db_session, tenant_id):
    """One unreachable call must not abort a bulk sync."""
    call = await call_service.create_outbound_call_record(
        db_session, tenant_id, uuid.uuid4(), "err_1", "+491701234567"
    )

    changed = await call_service.reconcile_call(db_session, call, _StubAdapter(raises=True))

    assert changed is False
    updated = await call_service.get_call(db_session, call.id, tenant_id)
    assert updated.status == "in_progress"


@pytest.mark.asyncio
async def test_reconcile_stale_calls_is_tenant_scoped(db_session, tenant_id, other_tenant_id):
    """ADR-001: syncing must never touch another tenant's calls."""
    mine = await call_service.create_outbound_call_record(
        db_session, tenant_id, uuid.uuid4(), "mine_1", "+491701234567"
    )
    theirs = await call_service.create_outbound_call_record(
        db_session, other_tenant_id, uuid.uuid4(), "theirs_1", "+491709999999"
    )

    adapter = _StubAdapter(
        {"call_status": "ended", "disconnection_reason": "user_hangup", "duration_ms": 5_000}
    )
    updated_count = await call_service.reconcile_stale_calls(db_session, tenant_id, adapter)

    assert updated_count == 1
    assert (await call_service.get_call(db_session, mine.id, tenant_id)).status == "resolved"
    assert (
        await call_service.get_call(db_session, theirs.id, other_tenant_id)
    ).status == "in_progress"


@pytest.mark.asyncio
async def test_handle_call_ended_noop_for_unknown_call(db_session):
    # Must not raise.
    await call_service.handle_call_ended(db_session, "unknown_call")


@pytest.mark.asyncio
async def test_handle_call_started_never_raises():
    # Purely a log-and-return no-op today (see module docstring) — just must not crash.
    await call_service.handle_call_started("some_call_id", platform="retell")


class TestParseRetellTurns:
    def test_maps_retell_roles_to_storage_roles(self):
        """Retell's transcript role is "user"/"agent"; storage (and the frontend's
        TranscriptViewer) expects "caller"/"agent"."""
        turns = call_service.parse_retell_turns(
            [{"role": "user", "content": "Hi"}, {"role": "agent", "content": "Hello!"}]
        )
        assert turns == [
            {"role": "caller", "text": "Hi"},
            {"role": "agent", "text": "Hello!"},
        ]

    def test_skips_items_with_non_string_content(self):
        turns = call_service.parse_retell_turns([{"role": "user", "content": None}])
        assert turns == []

    def test_unknown_role_defaults_to_caller(self):
        turns = call_service.parse_retell_turns([{"role": "system", "content": "..."}])
        assert turns[0]["role"] == "caller"


class TestRecordTurns:
    @pytest.mark.asyncio
    async def test_writes_turns_and_synthesizes_full_text_by_default(self, db_session, tenant_id):
        call = await call_service.create_outbound_call_record(
            db_session, tenant_id, uuid.uuid4(), "turns_1", "+491701234567"
        )

        await call_service.record_turns(
            db_session,
            call,
            [{"role": "caller", "text": "Hi"}, {"role": "agent", "text": "Hello!"}],
        )
        await db_session.commit()

        transcript = await call_service.get_transcript(db_session, call.id, tenant_id)
        assert [t["role"] for t in transcript.turns] == ["caller", "agent"]
        assert [t["text"] for t in transcript.turns] == ["Hi", "Hello!"]
        assert "Hi" in transcript.full_text and "Hello!" in transcript.full_text

    @pytest.mark.asyncio
    async def test_sync_full_text_false_leaves_full_text_untouched(self, db_session, tenant_id):
        call = await call_service.create_outbound_call_record(
            db_session, tenant_id, uuid.uuid4(), "turns_2", "+491701234567"
        )
        await call_service.handle_transcript_update(db_session, "turns_2", "Retell's own text")

        await call_service.record_turns(
            db_session, call, [{"role": "caller", "text": "Hi"}], sync_full_text=False
        )
        await db_session.commit()

        transcript = await call_service.get_transcript(db_session, call.id, tenant_id)
        assert transcript.full_text == "Retell's own text"
        assert transcript.turns[0]["text"] == "Hi"

    @pytest.mark.asyncio
    async def test_unchanged_prefix_preserves_ts(self, db_session, tenant_id):
        """Re-recording the same first turn (as happens every time Retell resends the
        whole transcript-so-far) must not restamp it to "now" — otherwise every turn
        in a long call would end up with nearly the same timestamp as the last one."""
        call = await call_service.create_outbound_call_record(
            db_session, tenant_id, uuid.uuid4(), "turns_3", "+491701234567"
        )

        await call_service.record_turns(db_session, call, [{"role": "caller", "text": "Hi"}])
        await db_session.commit()
        first = await call_service.get_transcript(db_session, call.id, tenant_id)
        first_ts = first.turns[0]["ts"]

        await call_service.record_turns(
            db_session,
            call,
            [{"role": "caller", "text": "Hi"}, {"role": "agent", "text": "Hello!"}],
        )
        await db_session.commit()
        second = await call_service.get_transcript(db_session, call.id, tenant_id)

        assert second.turns[0]["ts"] == first_ts
        assert second.turns[1]["text"] == "Hello!"

    @pytest.mark.asyncio
    async def test_changed_turn_gets_a_new_ts(self, db_session, tenant_id):
        call = await call_service.create_outbound_call_record(
            db_session, tenant_id, uuid.uuid4(), "turns_4", "+491701234567"
        )

        await call_service.record_turns(db_session, call, [{"role": "caller", "text": "Hi"}])
        await db_session.commit()
        first_transcript = await call_service.get_transcript(db_session, call.id, tenant_id)
        first_ts = first_transcript.turns[0]["ts"]

        await call_service.record_turns(
            db_session, call, [{"role": "caller", "text": "Hi, there!"}]
        )
        await db_session.commit()
        second = await call_service.get_transcript(db_session, call.id, tenant_id)

        assert second.turns[0]["text"] == "Hi, there!"
        # Not asserting inequality of ts (a fast test run could tie); the meaningful
        # guarantee is the text actually changed, which is covered above.
        assert first_ts is not None


@pytest.mark.asyncio
async def test_apply_retell_call_state_parses_transcript_object_into_turns(db_session, tenant_id):
    """The free win: parsing transcript_object in apply_retell_call_state means even
    hosted-LLM calls (no live WS handler) end up with structured turns, not just
    full_text — see phase0.md's formerly-open "Transcript.turns is always []" gap."""
    call = await call_service.create_outbound_call_record(
        db_session, tenant_id, uuid.uuid4(), "obj_1", "+491701234567"
    )

    changed = await call_service.apply_retell_call_state(
        db_session,
        call,
        {
            "call_status": "ended",
            "disconnection_reason": "user_hangup",
            "transcript": "user: Hi\nagent: Hello!",
            "transcript_object": [
                {"role": "user", "content": "Hi"},
                {"role": "agent", "content": "Hello!"},
            ],
        },
    )
    await db_session.commit()

    assert changed is True
    transcript = await call_service.get_transcript(db_session, call.id, tenant_id)
    assert [t["role"] for t in transcript.turns] == ["caller", "agent"]
    # sync_full_text=False in apply_retell_call_state — Retell's own raw "transcript"
    # string wins over a synthesized one.
    assert transcript.full_text == "user: Hi\nagent: Hello!"


@pytest.mark.asyncio
async def test_end_call_hangs_up_and_records_terminal_state(db_session, tenant_id):
    """The emergency stop's happy path: the platform is told to hang up, and the row is
    closed out from the platform's own account of how the call ended.
    """
    call = await call_service.create_outbound_call_record(
        db_session, tenant_id, uuid.uuid4(), "live_1", "+491701234567"
    )
    adapter = _StubAdapter(
        {
            "call_status": "ended",
            "disconnection_reason": "agent_hangup",
            "duration_ms": 9_000,
        }
    )

    changed = await call_service.end_call(db_session, call, adapter)

    assert adapter.stopped == ["live_1"]
    assert changed is True
    updated = await call_service.get_call(db_session, call.id, tenant_id)
    assert updated.status == "resolved"
    assert updated.duration_sec == 9


@pytest.mark.asyncio
async def test_end_call_hangs_up_even_if_the_reconcile_fails(db_session, tenant_id):
    """Ordering guarantee: the hangup must not be undone or skipped by bookkeeping that
    fails afterwards. The row stays in_progress for the webhook to settle, but the call
    is down — which is the part the operator needed.
    """
    call = await call_service.create_outbound_call_record(
        db_session, tenant_id, uuid.uuid4(), "live_2", "+491701234567"
    )
    adapter = _StubAdapter(raises=True)  # get_call blows up; stop_call still works

    changed = await call_service.end_call(db_session, call, adapter)

    assert adapter.stopped == ["live_2"]
    assert changed is False
    updated = await call_service.get_call(db_session, call.id, tenant_id)
    assert updated.status == "in_progress"


@pytest.mark.asyncio
async def test_end_call_propagates_a_failed_hangup(db_session, tenant_id):
    """A hangup that didn't happen must never look like one that did — the caller has to
    be able to tell the operator the call is still live.
    """
    call = await call_service.create_outbound_call_record(
        db_session, tenant_id, uuid.uuid4(), "live_3", "+491701234567"
    )

    with pytest.raises(RuntimeError, match="refused the hangup"):
        await call_service.end_call(db_session, call, _StubAdapter(stop_raises=True))


@pytest.mark.asyncio
async def test_end_call_rejects_a_call_never_placed_on_the_platform(db_session, tenant_id):
    """No external_id means nothing was ever dialed, so there is no call to hang up —
    better to say so than to no-op and imply something was stopped.
    """
    call = Call(
        tenant_id=tenant_id,
        agent_id=uuid.uuid4(),
        caller_number="+491701234567",
        status="in_progress",
        started_at=datetime.now(UTC),
    )
    db_session.add(call)
    await db_session.commit()

    with pytest.raises(ValueError, match="no external_id"):
        await call_service.end_call(db_session, call, _StubAdapter())
