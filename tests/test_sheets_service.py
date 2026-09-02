"""Tests for the Google Sheet prospect sync.

The Sheets HTTP calls and the service-account token are stubbed — what's under test is
the sync's own contract: column ownership (system columns never read back in), row
identity by id-then-phone rather than position, the callback queue, and the promise that
a row vanishing from the sheet never deletes a prospect.
"""

import uuid
from datetime import UTC, datetime

import pytest

from backend.models.call import Call
from backend.services import prospect_service, sheets_service

H = sheets_service.HEADER


class _FakeSheet:
    """Stands in for the Google Sheets API — holds a grid, records what was written."""

    def __init__(self, grid: list[list[str]] | None = None):
        self.grid = grid if grid is not None else []
        self.written: list[list[str]] | None = None
        # Every tab written this sync, keyed by tab name — the call list goes to its own.
        self.tabs: dict[str, list[list[str]]] = {}
        self.created_tabs: list[str] = []
        self.cleared_tabs: list[str] = []

    def install(self, monkeypatch):
        async def read(spreadsheet_id, sheet_name):
            return [list(r) for r in self.grid]

        async def write(spreadsheet_id, sheet_name, rows, last_column=None):
            self.tabs[sheet_name] = rows
            if sheet_name != sheets_service.CALL_LIST_SHEET:
                self.written = rows
                self.grid = rows

        async def create_tab(spreadsheet_id, sheet_name):
            self.created_tabs.append(sheet_name)
            return True

        async def clear(spreadsheet_id, sheet_name, last_column):
            self.cleared_tabs.append(sheet_name)

        monkeypatch.setattr(sheets_service, "_read_grid", read)
        monkeypatch.setattr(sheets_service, "_write_grid", write)
        monkeypatch.setattr(sheets_service, "create_tab", create_tab)
        monkeypatch.setattr(sheets_service, "_clear_grid", clear)
        return self

    def call_list(self) -> list[list[str]]:
        """Written call-list data rows (header dropped)."""
        return (self.tabs.get(sheets_service.CALL_LIST_SHEET) or [])[1:]

    def rows(self) -> list[list[str]]:
        """Written data rows (header dropped)."""
        return (self.written or [])[1:]

    def col(self, name: str, row_index: int = 0) -> str:
        return self.rows()[row_index][H.index(name)]


async def _prospect(db_session, tenant_id, name="SheetCo", phone="+442077335265", **extra):
    place = {"google_place_id": f"s_{uuid.uuid4().hex}", "name": name, "phone": phone, **extra}
    [p] = await prospect_service.upsert_from_places(db_session, tenant_id, [place], "q")
    return p


@pytest.mark.asyncio
async def test_first_run_populates_an_empty_sheet(db_session, tenant_id, monkeypatch):
    """The chosen onboarding path: point it at a blank sheet and it writes the header
    plus everything already in the database."""
    sheet = _FakeSheet([]).install(monkeypatch)
    await _prospect(db_session, tenant_id, "Alpha Roofing", "+442077335265")
    await _prospect(db_session, tenant_id, "Beta Roofing", "+442089453112")

    stats = await sheets_service.sync(db_session, tenant_id, "sid", "Sheet1")

    assert stats["rows_read"] == 0
    assert stats["created"] == 0
    assert stats["written"] == 2
    assert sheet.written[0] == H
    assert {r[H.index("Business name")] for r in sheet.rows()} == {"Alpha Roofing", "Beta Roofing"}
    # Every row carries its id, which is what makes the next sync position-independent.
    assert all(r[0] for r in sheet.rows())


@pytest.mark.asyncio
async def test_new_row_typed_by_hand_creates_a_prospect(db_session, tenant_id, monkeypatch):
    sheet = _FakeSheet(
        [H, ["", "Hand Typed Roofing", "020 7733 5265", "", "Bristol", "UK", "call mornings", ""]]
    ).install(monkeypatch)

    stats = await sheets_service.sync(db_session, tenant_id, "sid", "Sheet1")

    assert stats["created"] == 1
    rows = await prospect_service.list_prospects(db_session, tenant_id)
    assert len(rows) == 1
    assert rows[0].name == "Hand Typed Roofing"
    assert rows[0].city == "Bristol"
    assert rows[0].prospect_notes == "call mornings"
    # The id is written back so the row is stable across sorts from here on.
    assert sheet.col("id") == str(rows[0].id)


@pytest.mark.asyncio
async def test_hand_typed_row_matches_an_existing_prospect_by_phone(
    db_session, tenant_id, monkeypatch
):
    """National vs E.164 must not create a duplicate — the same phone_match_key bug that
    seeded five duplicate London roofers through the CSV path."""
    existing = await _prospect(db_session, tenant_id, "Dulwich Roofing", "+442077335265")
    _FakeSheet([H, ["", "Dulwich Roofing Ltd", "020 7733 5265", "", "", "", "", ""]]).install(
        monkeypatch
    )

    stats = await sheets_service.sync(db_session, tenant_id, "sid", "Sheet1")

    assert stats["created"] == 0
    assert len(await prospect_service.list_prospects(db_session, tenant_id)) == 1
    reloaded = await prospect_service.get_prospect(db_session, existing.id, tenant_id)
    assert reloaded.name == "Dulwich Roofing Ltd"  # sheet owns the name


@pytest.mark.asyncio
async def test_system_columns_are_never_read_back_in(db_session, tenant_id, monkeypatch):
    """Column ownership, which is the whole design. An operator typing "booked" into the
    Status column must not change anything — that column is output, not input."""
    p = await _prospect(db_session, tenant_id, "Alpha", "+442077335265")
    await prospect_service.set_status(db_session, p.id, tenant_id, "voicemail")

    sheet = _FakeSheet(
        [H, [str(p.id), "Alpha", "+442077335265", "", "", "", "", "", "booked", "99", "nonsense"]]
    ).install(monkeypatch)

    await sheets_service.sync(db_session, tenant_id, "sid", "Sheet1")

    reloaded = await prospect_service.get_prospect(db_session, p.id, tenant_id)
    assert reloaded.status == "voicemail"  # not "booked"
    assert reloaded.call_count == 0  # not 99
    assert sheet.col("Status") == "voicemail"  # push overwrote the operator's typing


@pytest.mark.asyncio
async def test_call_again_queues_a_callback_and_clears_the_box(db_session, tenant_id, monkeypatch):
    p = await _prospect(db_session, tenant_id, "Voicemail Co", "+442077335265")
    sheet = _FakeSheet(
        [H, [str(p.id), "Voicemail Co", "+442077335265", "", "", "", "", "TRUE"]]
    ).install(monkeypatch)

    stats = await sheets_service.sync(db_session, tenant_id, "sid", "Sheet1")

    assert stats["queued"] == 1
    reloaded = await prospect_service.get_prospect(db_session, p.id, tenant_id)
    assert reloaded.outreach_status == "callback"
    # Cleared on the way out, so one tick buys one retry rather than a re-dial loop.
    assert sheet.col("Call again?") == "FALSE"


@pytest.mark.asyncio
async def test_callback_prospect_is_eligible_despite_its_call_count(db_session, tenant_id):
    """The escape hatch batch_call_targets needs for a retry to be possible at all."""
    p = await _prospect(db_session, tenant_id, "Called Thrice", "+442077335265")
    p.call_count = 3
    await db_session.commit()

    assert await prospect_service.batch_call_targets(db_session, tenant_id, limit=10) == []

    await prospect_service.set_outreach_status(db_session, p.id, tenant_id, "callback")
    targets = await prospect_service.batch_call_targets(db_session, tenant_id, limit=10)
    assert [t.id for t in targets] == [p.id]

    # Dispatching consumes the flag, so the next run doesn't re-dial them forever. It
    # falls back to "not_reached", not "reached" — the dial went out, nobody answered yet.
    await prospect_service.record_call(db_session, p.id, tenant_id)
    reloaded = await prospect_service.get_prospect(db_session, p.id, tenant_id)
    assert reloaded.outreach_status == "not_reached"
    assert await prospect_service.batch_call_targets(db_session, tenant_id, limit=10) == []


@pytest.mark.asyncio
async def test_a_row_deleted_from_the_sheet_never_deletes_the_prospect(
    db_session, tenant_id, monkeypatch
):
    """An accidental sort-then-delete must not destroy real call history."""
    p = await _prospect(db_session, tenant_id, "Still Here", "+442077335265")
    sheet = _FakeSheet([H]).install(monkeypatch)  # header only — the row is gone

    await sheets_service.sync(db_session, tenant_id, "sid", "Sheet1")

    assert await prospect_service.get_prospect(db_session, p.id, tenant_id) is not None
    # ...and push puts it back, so the sheet self-heals rather than silently losing rows.
    assert sheet.col("Business name") == "Still Here"


@pytest.mark.asyncio
async def test_existing_rows_keep_their_position(db_session, tenant_id, monkeypatch):
    """Re-sorting the operator's view out from under them on every sync would make the
    sheet unusable, so sheet order wins over priority order for rows already present."""
    low = await _prospect(db_session, tenant_id, "Low", "+442077335265", rating=1.0)
    high = await _prospect(db_session, tenant_id, "High", "+442089453112", rating=5.0)
    assert high.priority_score > low.priority_score

    # Sheet has them in the "wrong" order relative to priority.
    sheet = _FakeSheet(
        [
            H,
            [str(low.id), "Low", "+442077335265", "", "", "", "", ""],
            [str(high.id), "High", "+442089453112", "", "", "", "", ""],
        ]
    ).install(monkeypatch)

    await sheets_service.sync(db_session, tenant_id, "sid", "Sheet1")

    assert [r[H.index("Business name")] for r in sheet.rows()] == ["Low", "High"]


@pytest.mark.asyncio
async def test_blank_cells_do_not_wipe_stored_values(db_session, tenant_id, monkeypatch):
    """Blank means "not filled in", not "clear it" — otherwise an operator who never
    typed a website would erase one research found."""
    p = await _prospect(
        db_session, tenant_id, "Alpha", "+442077335265", website="https://alpha.test"
    )
    _FakeSheet([H, [str(p.id), "Alpha", "+442077335265", "", "", "", "", ""]]).install(monkeypatch)

    await sheets_service.sync(db_session, tenant_id, "sid", "Sheet1")

    reloaded = await prospect_service.get_prospect(db_session, p.id, tenant_id)
    assert reloaded.website == "https://alpha.test"


@pytest.mark.asyncio
async def test_sync_is_tenant_scoped(db_session, tenant_id, other_tenant_id, monkeypatch):
    """A prospect id from another tenant in column A must not be reachable (ADR-001)."""
    theirs = await _prospect(db_session, other_tenant_id, "Not Yours", "+442077335265")
    sheet = _FakeSheet(
        [H, [str(theirs.id), "Renamed By Attacker", "+441170000000", "", "", "", "", ""]]
    ).install(monkeypatch)

    await sheets_service.sync(db_session, tenant_id, "sid", "Sheet1")

    untouched = await prospect_service.get_prospect(db_session, theirs.id, other_tenant_id)
    assert untouched.name == "Not Yours"
    # It fell through to "unknown row" and created a prospect under the syncing tenant.
    assert sheet.col("Business name") == "Renamed By Attacker"
    assert sheet.col("id") != str(theirs.id)


@pytest.mark.asyncio
async def test_half_typed_row_is_skipped_not_created(db_session, tenant_id, monkeypatch):
    _FakeSheet([H, ["", "Name But No Phone", "", "", "", "", "", ""]]).install(monkeypatch)

    stats = await sheets_service.sync(db_session, tenant_id, "sid", "Sheet1")

    assert stats["created"] == 0
    assert await prospect_service.list_prospects(db_session, tenant_id) == []


@pytest.mark.asyncio
async def test_phone_numbers_are_written_as_text_not_formulas(db_session, tenant_id, monkeypatch):
    """Every E.164 number starts with "+", which Sheets parses as a formula prefix under
    USER_ENTERED — the first real sync rendered the entire Phone column as #ERROR! and
    would have read those errors back as the prospects' numbers on the next pull.
    """
    await _prospect(db_session, tenant_id, "Alpha", "+442077335265")
    sheet = _FakeSheet([]).install(monkeypatch)

    await sheets_service.sync(db_session, tenant_id, "sid", "Sheet1")

    assert sheet.col("Phone") == "'+442077335265"
    # The tick box must stay a real boolean, so it is NOT escaped.
    assert sheet.col("Call again?") == "FALSE"


def test_text_escapes_only_formula_prefixes():
    assert sheets_service._text("+442077335265") == "'+442077335265"
    assert sheets_service._text("=1+1") == "'=1+1"
    assert sheets_service._text("-Acme") == "'-Acme"
    assert sheets_service._text("@handle") == "'@handle"
    # Leading zero: Sheets would parse "02075849173" as the number 2075849173 and the
    # next pull would read the truncated value back as the prospect's phone.
    assert sheets_service._text("02075849173") == "'02075849173"
    assert sheets_service._text("Acme Roofing") == "Acme Roofing"
    assert sheets_service._text("") == ""


# --- the call list tab ---------------------------------------------------------------
#
# The operator's callback order: engaged conversations first, then voicemail, then
# no-answer, then people who picked up and bailed. Dead numbers and settled prospects
# stay off it entirely.


def _latest(reason, duration=0, answered=None):
    return sheets_service.LatestCall(
        reason=reason, duration_sec=duration, answered_by_human=answered
    )


@pytest.mark.parametrize(
    ("status", "latest", "expected"),
    [
        # A real conversation — top of the list.
        ("called", _latest("user_hangup", 180, True), "engaged"),
        ("called", _latest("agent_hangup", 90, True), "engaged"),
        # Voicemail is decided by Retell's machine detection, NOT by our transcript
        # heuristic: the machine's own greeting transcribes as a turn from the far end, so
        # answered_by_human is True on every voicemail. Testing it first would file the
        # whole bucket under "engaged".
        ("voicemail", _latest("voicemail_reached", 30, True), "voicemail"),
        ("voicemail", _latest("machine_detected", 120, True), "voicemail"),
        # Rang out, declined, busy — the number is live, the moment was wrong.
        ("no_answer", _latest("dial_no_answer", 0, False), "no_answer"),
        ("no_answer", _latest("user_declined", 0, False), "no_answer"),
        ("no_answer", _latest("dial_busy", 0, None), "no_answer"),
        # Ended with nobody having spoken, for a reason we have no rule for.
        ("called", _latest("some_new_retell_reason", 4, False), "no_answer"),
        # Picked up and bailed.
        ("called", _latest("user_hangup", 12, True), "hung_up"),
        # Dead numbers: calling again does the same thing.
        ("no_answer", _latest("dial_failed", 0, False), None),
        ("no_answer", _latest("invalid_destination", 0, False), None),
        ("no_answer", _latest("marked_as_spam", 0, False), None),
        # Settled — already worked, or explicitly rejected.
        ("booked", _latest("user_hangup", 200, True), None),
        ("do_not_call", _latest("user_hangup", 200, True), None),
        ("flagged", _latest("user_hangup", 200, True), None),
        # Never dialled: there is nothing to call *back*.
        ("not_called", None, None),
    ],
)
def test_call_list_bucket(status, latest, expected):
    assert sheets_service.call_list_bucket(status, latest) == expected


def test_engaged_threshold_is_exclusive_at_sixty_seconds():
    """The one tuning knob for the whole answered-by-human half of the list, so pin both
    sides of it rather than only the obvious cases."""
    assert sheets_service.call_list_bucket("called", _latest("user_hangup", 60, True)) == "hung_up"
    assert sheets_service.call_list_bucket("called", _latest("user_hangup", 61, True)) == "engaged"


def test_voicemail_definition_matches_prospect_service():
    """Two modules decide "was this a machine" and they must not drift — the classifier
    got this wrong once already and mislabelled a whole campaign of voicemails."""
    for reason in prospect_service.VOICEMAIL_REASONS:
        assert (
            sheets_service.call_list_bucket("voicemail", _latest(reason, 30, True)) == "voicemail"
        )


@pytest.mark.asyncio
async def test_call_list_orders_by_bucket_then_coldest_first(db_session, tenant_id):
    """The whole point of the tab: bucket order first, and inside a bucket the least-
    dialled, longest-untouched prospect comes up before one already chased three times."""
    made = []
    for name, status, call_count, last_called in (
        ("Hung Up Co", "called", 1, datetime(2026, 8, 1, tzinfo=UTC)),
        ("No Answer Co", "no_answer", 1, datetime(2026, 8, 1, tzinfo=UTC)),
        ("Voicemail Chased", "voicemail", 3, datetime(2026, 8, 1, tzinfo=UTC)),
        ("Voicemail Cold", "voicemail", 1, datetime(2026, 7, 1, tzinfo=UTC)),
        ("Voicemail Warm", "voicemail", 1, datetime(2026, 8, 1, tzinfo=UTC)),
        ("Engaged Co", "called", 2, datetime(2026, 8, 1, tzinfo=UTC)),
    ):
        p = await _prospect(db_session, tenant_id, name, f"+4420{len(made):08d}")
        p.status = status
        p.call_count = call_count
        p.last_called_at = last_called
        made.append(p)
    await db_session.commit()

    latest = {
        made[0].id: _latest("user_hangup", 10, True),
        made[1].id: _latest("dial_no_answer", 0, False),
        made[2].id: _latest("voicemail_reached", 20, True),
        made[3].id: _latest("voicemail_reached", 20, True),
        made[4].id: _latest("voicemail_reached", 20, True),
        made[5].id: _latest("user_hangup", 240, True),
    }

    rows = sheets_service._build_call_list(made, latest)

    assert rows[0] == sheets_service.CALL_LIST_HEADER
    name_col = sheets_service.CALL_LIST_HEADER.index("Business name")
    assert [r[name_col] for r in rows[1:]] == [
        "Engaged Co",
        # Same bucket: fewest calls first, then coldest last-called, then the chased one.
        "Voicemail Cold",
        "Voicemail Warm",
        "Voicemail Chased",
        "No Answer Co",
        "Hung Up Co",
    ]
    bucket_col = sheets_service.CALL_LIST_HEADER.index("Bucket")
    assert rows[1][bucket_col] == "Engaged"


@pytest.mark.asyncio
async def test_sync_writes_the_call_list_to_its_own_tab(db_session, tenant_id, monkeypatch):
    """End to end: the tab is provisioned, cleared, and written — and the main tab keeps
    its own ordering, untouched by the call list's."""
    sheet = _FakeSheet([]).install(monkeypatch)
    p = await _prospect(db_session, tenant_id, "Voicemail Co", "+442077335265")
    p.status = "voicemail"
    p.call_count = 1
    db_session.add(
        Call(
            tenant_id=tenant_id,
            agent_id=uuid.uuid4(),
            caller_number="+442077335265",
            prospect_id=p.id,
            status="failed",
            disconnection_reason="voicemail_reached",
            duration_sec=22,
            answered_by_human=True,
            started_at=datetime(2026, 8, 30, tzinfo=UTC),
        )
    )
    await db_session.commit()

    stats = await sheets_service.sync(db_session, tenant_id, "sid", "Sheet1")

    assert sheets_service.CALL_LIST_SHEET in sheet.created_tabs
    # Cleared before the write: a shrinking list would otherwise leave stale rows below
    # it that read as live callbacks.
    assert sheets_service.CALL_LIST_SHEET in sheet.cleared_tabs
    assert stats["call_list_written"] == 1
    [row] = sheet.call_list()
    assert row[sheets_service.CALL_LIST_HEADER.index("Bucket")] == "Voicemail"
    assert row[sheets_service.CALL_LIST_HEADER.index("Last outcome")] == "voicemail_reached"
    assert row[sheets_service.CALL_LIST_HEADER.index("Last duration")] == "22"
    # Phones stay text on this tab too — a leading "+" would render as #ERROR! otherwise.
    assert row[sheets_service.CALL_LIST_HEADER.index("Phone")] == "'+442077335265"
    # The main tab still carries the raw reason in its own "Last outcome" column.
    assert sheet.col("Last outcome") == "voicemail_reached"


@pytest.mark.asyncio
async def test_an_in_progress_call_keeps_a_prospect_off_the_call_list(
    db_session, tenant_id, monkeypatch
):
    """A call that has not ended has no outcome to bucket on, and a prospect dialled but
    never resolved must not show up as a no-answer callback."""
    sheet = _FakeSheet([]).install(monkeypatch)
    p = await _prospect(db_session, tenant_id, "Mid Call Co", "+442077335265")
    db_session.add(
        Call(
            tenant_id=tenant_id,
            agent_id=uuid.uuid4(),
            caller_number="+442077335265",
            prospect_id=p.id,
            status="in_progress",
            started_at=datetime(2026, 8, 30, tzinfo=UTC),
        )
    )
    await db_session.commit()

    await sheets_service.sync(db_session, tenant_id, "sid", "Sheet1")

    assert sheet.call_list() == []
