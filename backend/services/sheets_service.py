"""Two-way prospect sync with a Google Sheet, run on demand by the operator.

**This is deliberately not a live bidirectional sync**, and the reason is worth stating
because "keep them in sync automatically" is the obvious-sounding thing to build instead.

Google Sheets has no cell-edit webhook. The available push mechanisms are an Apps Script
`onEdit` trigger installed inside the document (and the *simple* trigger can't even make
external requests — it runs in restricted auth mode) or a Drive `files.watch` channel
that tells you "something changed" without saying what, and expires on a timer. Neither
is a change feed. Worse, a genuine two-way sync needs conflict resolution, and Sheets
gives you no per-cell modified timestamp and no per-row revision to resolve *with* — you
would be merging blind and silently losing edits.

So the design removes the conflict rather than resolving it, in two ways:

1. **Column ownership.** Every column belongs to exactly one writer (see COLUMNS below).
   The operator owns the list itself; this backend owns the call outcomes. Nothing has
   two writers, so a conflict is structurally impossible rather than merely unlikely.
2. **Manual trigger.** The operator presses "Sync sheet" and *is* the serializer — they
   know whether they just edited the sheet or just ran a batch of calls. No background
   job races them.

One sync = pull, then push, in that order. Pull first so the operator's edits are in the
database before it writes state back out; because the two column sets are disjoint, that
ordering is always safe and the whole thing is re-runnable.

**Row identity is `prospect_id` in hidden column A, never the row number.** Operators
sort and filter sheets constantly; keying on position would write "voicemail" onto
whichever company happened to land in row 5 after a sort. Rows typed by hand have no id
yet, so they're matched on `prospect_service.phone_match_key` and then have their id
written back.

**A row removed from the sheet is never deleted from the database.** An accidental
sort-then-delete would otherwise destroy real call history. Deletion stays an explicit
act in the app.

**Two tabs, and only the first one is two-way.** The main tab above is the editable
master and keeps the operator's row order forever, which is what makes it safe to edit
but also what makes it useless as a work queue — it grows in discovery order and never
says who to call next. So the sync also writes a second **"Call list"** tab, regenerated
top-to-bottom every run, ordered by callback priority (see CALL_LIST_SHEET below).

That tab is *exempt* from the two-writer problem rather than solving it: every column is
system-owned and it is never read back in, so an operator edit there has nothing to
collide with — it is simply overwritten next sync. Operators still act on the main tab;
the call list is the reading order they work through.
"""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.models.call import Call
from backend.models.prospect import Prospect
from backend.services import prospect_service

logger = logging.getLogger(__name__)
settings = get_settings()

BASE_URL = "https://sheets.googleapis.com/v4/spreadsheets"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


class SheetSyncError(Exception):
    """The sheet is unreachable, unconfigured, or shaped wrong — surfaced as a 422/502."""


# The contract with the sheet, in column order starting at A.
#
# `owner` is the whole design (see module docstring):
#   "sheet"  — the operator edits it; pull reads it into the database
#   "system" — this backend computes it; push overwrites it every sync
#
# Operator-owned columns sit on the left where they're comfortable to edit, system-owned
# on the right, and the id hides in A. Anything to the right of the last column here is
# left alone — the written range is bounded — so an operator's own extra notes column
# survives a sync.
COLUMNS: list[tuple[str, str]] = [
    ("id", "system"),  # A — hidden; the join key, NOT the row number
    ("Business name", "sheet"),  # B
    ("Phone", "sheet"),  # C
    ("Website", "sheet"),  # D
    ("City", "sheet"),  # E
    ("Country", "sheet"),  # F
    ("Notes", "sheet"),  # G
    ("Call again?", "sheet"),  # H — tick to queue for the next batch call
    ("Status", "system"),  # I
    ("Calls", "system"),  # J
    ("Last called", "system"),  # K
    ("Last outcome", "system"),  # L
]

HEADER = [name for name, _ in COLUMNS]
LAST_COLUMN = chr(ord("A") + len(COLUMNS) - 1)  # "L"


# --- the call list tab ---------------------------------------------------------------
#
# A SECOND tab, and unlike the one above it is regenerated top-to-bottom on every sync:
# it answers "who do I call next", which is an ordering, and an ordering can't survive
# the main tab's rule that existing rows keep their position.
#
# It is exempt from the two-writer problem rather than solving it: every column is
# system-owned and the tab is never read back in, so there is nothing on it for an
# operator's edit to collide with. Operators still act on the *Prospects* tab — tick
# "Call again?" there — and this tab is the reading order they work through.
CALL_LIST_SHEET = "Call list"
CALL_LIST_HEADER = [
    "Bucket",
    "Business name",
    "Phone",
    "City",
    "Calls",
    "Last called",
    "Last outcome",
    "Last duration",
    "Notes",
    "id",
]
CALL_LIST_LAST_COLUMN = chr(ord("A") + len(CALL_LIST_HEADER) - 1)  # "J"

# A call where a person picked up and stayed on this long is a live conversation, and
# the operator wants those at the top. Below it, the same "a human answered" population
# means the opposite thing — they picked up and bailed. One knob splits both buckets.
ENGAGED_MIN_SEC = 60

# Retell disconnection_reasons meaning "it rang and nobody took it" — the number is fine,
# the moment was wrong, so it is worth another dial. Distinct from the dead reasons below,
# which Call.status collapses into the same "failed" as these.
_NO_ANSWER_REASONS = {"dial_no_answer", "user_declined", "dial_busy"}

# The number itself is the problem. Calling again does the same thing, so these are kept
# off the list entirely rather than parked at the bottom.
_DEAD_REASONS = {
    "dial_failed",
    "invalid_destination",
    "marked_as_spam",
    "telephony_provider_permission_denied",
    "telephony_provider_unavailable",
    "sip_routing_error",
}

# Off the list because the operator has already settled them: booked and do_not_call are
# operator-set, and flagged means a human heard the pitch and the post-call sentiment came
# back negative. Putting a rejection at the top of a callback list — which the >60s rule
# would otherwise do, since a rejection is a long answered call — is the opposite of what
# the ordering is for.
_SETTLED_STATUSES = {"booked", "do_not_call", "flagged"}

# Bucket order = call order. Index is the sort rank.
CALL_LIST_BUCKETS = ["engaged", "voicemail", "no_answer", "hung_up"]
_BUCKET_LABELS = {
    "engaged": "Engaged",
    "voicemail": "Voicemail",
    "no_answer": "No answer",
    "hung_up": "Hung up",
}

# Only a terminal call says anything about how the prospect responded; an in_progress row
# has no outcome yet. Same set resync_status_from_calls filters on.
_TERMINAL_CALL_STATUSES = ("resolved", "escalated", "failed")


@dataclass(frozen=True)
class LatestCall:
    """The prospect's most recent terminal call, flattened to just what the sheet needs."""

    reason: str
    duration_sec: int
    answered_by_human: bool | None


def call_list_bucket(status: str, latest: LatestCall | None) -> str | None:
    """Which call-list bucket a prospect belongs in, or None to keep it off the list.

    Pure, and deliberately decided from the prospect's LATEST call rather than the best
    one across its history. That is the opposite of prospect_service.resync_status_from_calls,
    and the divergence is intentional: `Prospect.status` answers "how far did we ever get
    with this company", where the best-ever outcome is the fact worth keeping. This answers
    "what should I do next", where only the most recent attempt is informative — a prospect
    who spoke to us in June and hit voicemail last night is a voicemail callback today.
    """
    if status in _SETTLED_STATUSES:
        return None
    if latest is None:
        return None  # never dialled, or no terminal call yet — nothing to call *back*

    reason = (latest.reason or "").lower()
    if reason in _DEAD_REASONS:
        return None

    # Tested BEFORE answered_by_human, and the order is load-bearing for the same reason
    # it is in prospect_service.outcome_status_for_call: an answering machine's outgoing
    # greeting transcribes as a turn from the far end, so every voicemail looks like a
    # human who talked. Retell's own machine detection is the authority here; our
    # transcript heuristic is not.
    if reason in prospect_service.VOICEMAIL_REASONS:
        return "voicemail"
    if latest.answered_by_human:
        return "engaged" if latest.duration_sec > ENGAGED_MIN_SEC else "hung_up"
    if reason in _NO_ANSWER_REASONS:
        return "no_answer"
    # Anything else that ended without a human on the line: a "resolved" call with zero
    # caller turns, an unmapped reason, a reason we've never seen. It rang and nothing
    # came of it, which is the no-answer bucket.
    return "no_answer"


# Sheets renders a real checkbox as TRUE/FALSE, but operators also type things. Accepted
# spellings for "yes, call this one again" — anything else (including blank) is False.
_TRUTHY = {"true", "yes", "y", "1", "x", "✓", "✔"}


def _col(row: list[str], index: int) -> str:
    """Cell at `index`, or "" — Sheets truncates trailing empty cells, so a short row is
    normal rather than malformed and must not IndexError."""
    return row[index].strip() if index < len(row) and row[index] else ""


# Google's OAuth2 JWT-bearer grant, per the service-account flow.
_JWT_GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"
_TOKEN_TTL_SEC = 3600
# Refresh a little early so a token can't expire between the read and the write of one
# sync — a 401 halfway through would leave the sheet partially written.
_TOKEN_REFRESH_MARGIN_SEC = 300

# (token, expires_at_monotonic). Process-local, and only ever holds a short-lived bearer
# token — never the private key.
_token_cache: tuple[str, float] | None = None


def _signed_assertion(path: str) -> tuple[str, str]:
    """Build the signed JWT assertion and return it with the token endpoint to send it to.

    Deliberately does NOT use google-auth's own `refresh()`: that path goes through
    `google.auth.transport.requests`, which needs the `requests` library — a whole
    synchronous HTTP stack pulled in for a single token call, in a service that talks to
    every other API with httpx. Only the crypto is borrowed (signing an RS256 JWT by hand
    is not worth reimplementing); the exchange below is an ordinary async HTTP request.
    """
    # Imported here, not at module import time: the app must load fine on an install
    # that never configured Sheets.
    from google.auth import crypt, jwt

    try:
        info = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SheetSyncError(f"Could not read the service-account key at {path}: {exc}") from exc

    try:
        signer = crypt.RSASigner.from_service_account_info(info)
        token_uri = str(info["token_uri"])
        issuer = str(info["client_email"])
    except (KeyError, ValueError) as exc:
        raise SheetSyncError(
            f"{path} is not a valid service-account key ({exc}). Download a fresh JSON key "
            "from Google Cloud Console -> Service Accounts -> Keys."
        ) from exc

    now = int(time.time())
    assertion = jwt.encode(
        signer,
        {
            "iss": issuer,
            "scope": " ".join(SCOPES),
            "aud": token_uri,
            "iat": now,
            "exp": now + _TOKEN_TTL_SEC,
        },
    )
    return assertion.decode("utf-8"), token_uri


async def _access_token() -> str:
    """A bearer token for the Sheets API, cached until shortly before it expires."""
    global _token_cache

    if _token_cache and time.monotonic() < _token_cache[1]:
        return _token_cache[0]

    path = settings.google_sheets_credentials_file
    if not path:
        raise SheetSyncError(
            "GOOGLE_SHEETS_CREDENTIALS_FILE is not set. Point it at the service-account "
            "JSON key, and share the sheet with that account's email as an Editor."
        )

    # Signing is CPU-bound (RSA) and file I/O is blocking, so both stay off the event loop.
    assertion, token_uri = await asyncio.to_thread(_signed_assertion, path)

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(token_uri, data={"grant_type": _JWT_GRANT, "assertion": assertion})
    if resp.status_code >= 400:
        raise SheetSyncError(
            f"Google rejected the service-account credentials ({resp.status_code}): {resp.text}"
        )

    token = str(resp.json().get("access_token") or "")
    if not token:
        raise SheetSyncError("Google returned no access_token for the service account.")

    _token_cache = (token, time.monotonic() + _TOKEN_TTL_SEC - _TOKEN_REFRESH_MARGIN_SEC)
    return token


async def list_tabs(spreadsheet_id: str) -> list[str]:
    """Tab names in the spreadsheet.

    Exists because targeting the wrong tab is destructive: _write_grid overwrites
    A1:L{n}, so pointing a sync at a tab that holds something else silently destroys it.
    Callers should confirm the target exists — and what's in it — before syncing.
    """
    token = await _access_token()
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{BASE_URL}/{spreadsheet_id}",
            headers={"Authorization": f"Bearer {token}"},
            params={"fields": "sheets.properties.title"},
        )
    if resp.status_code >= 400:
        raise SheetSyncError(
            f"Could not read the spreadsheet's tabs ({resp.status_code}): {resp.text}"
        )
    return [s["properties"]["title"] for s in (resp.json().get("sheets") or [])]


async def create_tab(spreadsheet_id: str, sheet_name: str) -> bool:
    """Add an empty tab. Returns False if one by that name already exists.

    The safe way to point a sync at a spreadsheet that already holds real work: a new tab
    can't clobber anything, whereas reusing an existing one overwrites it on the first
    push. Deliberately a no-op rather than an error when the tab is present, so it can be
    called ahead of a sync unconditionally.
    """
    if sheet_name in await list_tabs(spreadsheet_id):
        return False

    token = await _access_token()
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{BASE_URL}/{spreadsheet_id}:batchUpdate",
            headers={"Authorization": f"Bearer {token}"},
            json={"requests": [{"addSheet": {"properties": {"title": sheet_name}}}]},
        )
    if resp.status_code >= 400:
        raise SheetSyncError(
            f"Could not create tab '{sheet_name}' ({resp.status_code}): {resp.text}"
        )
    return True


async def _read_grid(spreadsheet_id: str, sheet_name: str) -> list[list[str]]:
    """Every populated row in the synced column range, header included."""
    token = await _access_token()
    rng = f"{sheet_name}!A:{LAST_COLUMN}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{BASE_URL}/{spreadsheet_id}/values/{rng}",
            headers={"Authorization": f"Bearer {token}"},
        )
    if resp.status_code == 403:
        raise SheetSyncError(
            "Google refused access to that spreadsheet (403). Share it with the service "
            "account's email address as an Editor."
        )
    if resp.status_code == 404:
        raise SheetSyncError(
            f"No spreadsheet '{spreadsheet_id}' (404). Check the id, and that the tab is "
            f"named '{sheet_name}'."
        )
    if resp.status_code == 400 and "Unable to parse range" in resp.text:
        # Sheets reports a missing TAB as an unparseable range, which reads like a bug in
        # our range syntax rather than what it is. Name the real cause and the real tabs.
        try:
            available = ", ".join(repr(t) for t in await list_tabs(spreadsheet_id))
        except SheetSyncError:
            available = "(could not list them)"
        raise SheetSyncError(
            f"No tab named '{sheet_name}' in that spreadsheet. Available tabs: {available}."
        )
    if resp.status_code >= 400:
        raise SheetSyncError(f"Google Sheets rejected the read ({resp.status_code}): {resp.text}")
    return [list(row) for row in (resp.json().get("values") or [])]


async def _clear_grid(spreadsheet_id: str, sheet_name: str, last_column: str) -> None:
    """Empty a tab's synced columns.

    Only the call-list tab needs this, and it needs it because that tab is a *list* whose
    length changes: when a prospect drops off it (booked, or its number went dead) the
    rewrite is shorter than what's there and the tail rows survive underneath, reading as
    live callbacks. The main tab is exempt — its row set only ever grows.
    """
    token = await _access_token()
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{BASE_URL}/{spreadsheet_id}/values/{sheet_name}!A:{last_column}:clear",
            headers={"Authorization": f"Bearer {token}"},
            json={},
        )
    if resp.status_code >= 400:
        raise SheetSyncError(
            f"Google Sheets rejected the clear of '{sheet_name}' ({resp.status_code}): {resp.text}"
        )


async def _write_grid(
    spreadsheet_id: str, sheet_name: str, rows: list[list[str]], last_column: str = LAST_COLUMN
) -> None:
    """Overwrite the synced range with `rows` (header first). One request, not one per
    row — Sheets' per-user write quota is 60/min, which a row-at-a-time loop would burn
    through on a list this size."""
    token = await _access_token()
    rng = f"{sheet_name}!A1:{last_column}{len(rows)}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.put(
            f"{BASE_URL}/{spreadsheet_id}/values/{rng}",
            headers={"Authorization": f"Bearer {token}"},
            # USER_ENTERED so a TRUE in "Call again?" lands as a real boolean the
            # operator's checkbox can render, rather than the literal string "TRUE".
            params={"valueInputOption": "USER_ENTERED"},
            json={"values": rows},
        )
    if resp.status_code >= 400:
        raise SheetSyncError(f"Google Sheets rejected the write ({resp.status_code}): {resp.text}")


def _text(value: str) -> str:
    """Force a value to be stored as text rather than parsed by Sheets.

    Non-negotiable for phone numbers, which get mangled two different ways under
    valueInputOption=USER_ENTERED — both observed on real data:

      "+44 7388 839522" -> #ERROR!      ("+" is a formula prefix, like "=", and the
                                         spaces make the formula a syntax error)
      "+442039664113"   -> 442039664113 (a *valid* formula: unary plus on a number)
      "02075849173"     -> 2075849173   (parsed as a number, leading zero dropped)

    The second and third are the dangerous ones: they look like data rather than errors,
    so the next pull reads them back as the prospect's number and overwrites the real one.
    A leading apostrophe is Sheets' own "this is text" marker and is stripped again on
    read, so the round trip is clean.

    USER_ENTERED is kept rather than switching the write to RAW because the "Call again?"
    column has to arrive as a real boolean for the operator's tick box to render it; RAW
    would store the string "TRUE" and break the checkbox.
    """
    # "0" is in the set for leading-zero national numbers; over-escaping an ordinary
    # string is harmless, since the apostrophe never survives to the read side.
    return "'" + value if value and value[0] in "=+-@0" else value


def _reason_of(latest: "LatestCall | None") -> str:
    """The main tab's "Last outcome" cell — the raw disconnection_reason, or blank."""
    return latest.reason if latest else ""


def _row_for(prospect: Prospect, last_outcome: str) -> list[str]:
    """One sheet row for a prospect. System columns are computed; sheet-owned columns are
    echoed back as stored, which is what makes a normalization (a tidied phone number) or
    an app-side edit visible in the sheet on the next sync."""
    return [
        str(prospect.id),  # a uuid — never formula-shaped
        _text(prospect.name or ""),
        _text(prospect.phone or ""),  # "+44..." would otherwise become #ERROR!
        _text(prospect.website or ""),
        _text(prospect.city or ""),
        _text(prospect.country or ""),
        _text(prospect.prospect_notes or ""),
        # Always cleared: a tick means "queue this", and pull has just consumed it. Left
        # set, it would re-queue the prospect on every future sync. Deliberately NOT
        # passed through _text — this one must land as a boolean for the tick box.
        "FALSE",
        prospect.status,
        str(prospect.call_count),  # a number, and wanted as one
        prospect.last_called_at.strftime("%Y-%m-%d %H:%M") if prospect.last_called_at else "",
        last_outcome,
    ]


async def _last_outcomes(db: AsyncSession, tenant_id: uuid.UUID) -> dict[Any, LatestCall]:
    """Most recent terminal call per prospect — the granular "what happened" behind the
    coarser Prospect.status ("user_hangup" vs "voicemail_reached" vs "dial_no_answer"),
    plus the duration and who answered, which is what the call list buckets on. One query
    for the whole tenant, not one per row."""
    rows = await db.execute(
        select(
            Call.prospect_id,
            Call.disconnection_reason,
            Call.duration_sec,
            Call.answered_by_human,
            Call.status,
            Call.started_at,
        )
        .where(Call.tenant_id == tenant_id, Call.prospect_id.is_not(None))
        .order_by(Call.started_at.desc())
    )
    latest: dict[Any, LatestCall] = {}
    for prospect_id, reason, duration, answered, status, _started in rows.all():
        # Ordered newest-first, so the first sighting of a prospect is its latest call.
        if prospect_id in latest:
            continue
        if not reason or status not in _TERMINAL_CALL_STATUSES:
            continue
        latest[prospect_id] = LatestCall(
            reason=reason,
            duration_sec=duration or 0,
            answered_by_human=answered,
        )
    return latest


def _build_call_list(
    prospects: list[Prospect], latest_by_id: dict[Any, LatestCall]
) -> list[list[str]]:
    """The call-list tab's full grid, header first — bucket order, then coldest-first.

    Pure: takes what it needs and returns rows, so the ordering is testable without any
    HTTP. Within a bucket the tie-breaks are, in order:

      call_count ascending   — don't spend a 4th dial on one company before a 1st on another
      last_called_at ascending — coldest first; never-called sorts to the top of its bucket
      priority_score descending — the discovery ranking, as the final tie-break

    last_called_at is compared as a POSIX timestamp rather than a datetime so a naive row
    (older data) can't raise against a tz-aware one mid-sort.
    """
    ranked: list[tuple[tuple[int, int, float, float], Prospect, str, LatestCall]] = []
    for prospect in prospects:
        latest = latest_by_id.get(prospect.id)
        bucket = call_list_bucket(prospect.status, latest)
        if bucket is None:
            continue
        assert latest is not None  # call_list_bucket returns None without one
        key = (
            CALL_LIST_BUCKETS.index(bucket),
            prospect.call_count,
            prospect.last_called_at.timestamp() if prospect.last_called_at else 0.0,
            -prospect.priority_score,
        )
        ranked.append((key, prospect, bucket, latest))
    ranked.sort(key=lambda item: item[0])

    rows = [CALL_LIST_HEADER]
    for _key, prospect, bucket, latest in ranked:
        rows.append(
            [
                _BUCKET_LABELS[bucket],
                _text(prospect.name or ""),
                _text(prospect.phone or ""),  # "+44..." would otherwise become #ERROR!
                _text(prospect.city or ""),
                str(prospect.call_count),
                prospect.last_called_at.strftime("%Y-%m-%d %H:%M")
                if prospect.last_called_at
                else "",
                latest.reason,
                str(latest.duration_sec),
                _text(prospect.prospect_notes or ""),
                str(prospect.id),
            ]
        )
    return rows


async def sync(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    spreadsheet_id: str,
    sheet_name: str,
    *,
    pull: bool = True,
) -> dict:
    """Pull the operator's edits in, then push system state back out. Returns counts.

    Safe to run repeatedly: pull is an upsert keyed on id-then-phone, push rewrites the
    same bounded range. See the module docstring for why this ordering is always correct.

    `pull=False` makes it push-only: the database overwrites the sheet and nothing is read
    back in. That exists for one specific situation — **after repairing prospect data
    out-of-band, push before you sync.** The sheet wins for operator-owned columns, so an
    ordinary sync run against a sheet that still holds the bad values will faithfully pull
    them straight back over the repair. (Learned the hard way: a phone-column fix was
    silently reverted by the very next sync.)
    """
    stats = dict.fromkeys(
        ("rows_read", "created", "updated", "queued", "written", "call_list_written"), 0
    )

    # Still read on a push-only run: the existing rows are what preserve row order below,
    # so skipping the read would reshuffle the operator's view.
    grid = await _read_grid(spreadsheet_id, sheet_name)
    # An empty sheet is the first-run case, not an error — push below populates it.
    body = grid[1:] if grid else []
    stats["rows_read"] = len(body)

    by_id = {
        str(p.id): p
        for p in (
            await db.execute(select(Prospect).where(Prospect.tenant_id == tenant_id))
        ).scalars()
    }
    by_phone: dict[str, Prospect] = {}
    for known in by_id.values():
        key = prospect_service.phone_match_key(known.phone)
        if key and key not in by_phone:
            by_phone[key] = known

    # --- pull -----------------------------------------------------------------------
    seen: set[str] = set()
    for row in body if pull else []:
        row_id = _col(row, 0)
        name = _col(row, 1)
        phone = _col(row, 2)
        if not name and not phone:
            continue  # a blank spacer row, not a prospect

        target = by_id.get(row_id)
        if target is None:
            key = prospect_service.phone_match_key(phone)
            target = by_phone.get(key) if key else None
        created = False
        if target is None:
            stored_phone = prospect_service.normalize_phone(phone)
            if not name or not stored_phone:
                continue  # a half-typed new row — wait until it has both
            target = Prospect(
                tenant_id=tenant_id,
                # Mirrors import_from_csv's convention: not a Places row, but the column
                # is NOT NULL and (tenant, place_id) is the pipeline's identity key.
                google_place_id=f"sheet:{stored_phone}",
                name=name,
                phone=stored_phone,
                priority_score=prospect_service.compute_priority(None, 0, None, stored_phone),
            )
            db.add(target)
            await db.flush()
            by_id[str(target.id)] = target
            key = prospect_service.phone_match_key(stored_phone)
            if key:
                by_phone[key] = target
            stats["created"] += 1
            created = True

        # Apply the operator-owned columns — for a brand-new row as well as an existing
        # one, which is why this is not an `else`. A hand-typed row usually arrives with
        # city/website/notes already filled in, and creating from name+phone alone
        # silently dropped every other cell the operator had typed.
        #
        # System columns are never read: they're stale output from the last push, and
        # treating them as input is exactly the two-writer problem this design avoids.
        changed = False
        for value, attr in (
            (name, "name"),
            (prospect_service.normalize_phone(phone) or "", "phone"),
            (prospect_service.normalize_website(_col(row, 3)) or "", "website"),
            (_col(row, 4), "city"),
            (_col(row, 5), "country"),
            (_col(row, 6), "prospect_notes"),
        ):
            # Blank means "not filled in", not "clear it" — an operator who hasn't
            # typed a website should not wipe one that research found.
            if value and getattr(target, attr) != value:
                setattr(target, attr, value)
                changed = True
        if changed and not created:
            stats["updated"] += 1

        if _col(row, 7).lower() in _TRUTHY and target.outreach_status != "do_not_call":
            # The callback queue. batch_call_targets treats "callback" as always eligible,
            # bypassing the call_count ceiling — that's the whole point of ticking the box
            # for a prospect who has already been dialled and went to voicemail.
            target.outreach_status = "callback"
            stats["queued"] += 1

        seen.add(str(target.id))

    await db.commit()

    # --- push -----------------------------------------------------------------------
    last_outcomes = await _last_outcomes(db, tenant_id)
    all_prospects = (
        (
            await db.execute(
                select(Prospect)
                .where(Prospect.tenant_id == tenant_id)
                .order_by(Prospect.priority_score.desc())
            )
        )
        .scalars()
        .all()
    )
    remaining = {str(p.id): p for p in all_prospects}

    # Rows the sheet already has keep their position — re-sorting the operator's view out
    # from under them on every sync would make the sheet unusable. Everything else (a
    # Places discovery, a CSV import, a row created just above) is appended below.
    rows: list[list[str]] = [HEADER]
    for row in body:
        row_id = _col(row, 0)
        prospect: Prospect | None = remaining.pop(row_id, None)
        if prospect is None:
            # No id in column A — the row the operator typed by hand this round. Resolve
            # it the same way pull did, so it lands back in its own position rather than
            # being appended as a second copy below.
            key = prospect_service.phone_match_key(_col(row, 2))
            match = by_phone.get(key) if key else None
            if match is not None:
                prospect = remaining.pop(str(match.id), None)
        if prospect is not None:
            rows.append(_row_for(prospect, _reason_of(last_outcomes.get(prospect.id))))
    for prospect in all_prospects:
        if str(prospect.id) in remaining:
            rows.append(_row_for(prospect, _reason_of(last_outcomes.get(prospect.id))))

    await _write_grid(spreadsheet_id, sheet_name, rows)
    stats["written"] = len(rows) - 1

    # --- the call list ----------------------------------------------------------------
    # Same prospects, same outcomes, no extra queries — only a different ordering, written
    # to its own tab. create_tab is a no-op when it already exists, so the first sync after
    # this shipped provisions the tab rather than failing on a missing range.
    call_list = _build_call_list(list(all_prospects), last_outcomes)
    await create_tab(spreadsheet_id, CALL_LIST_SHEET)
    await _clear_grid(spreadsheet_id, CALL_LIST_SHEET, CALL_LIST_LAST_COLUMN)
    await _write_grid(spreadsheet_id, CALL_LIST_SHEET, call_list, CALL_LIST_LAST_COLUMN)
    stats["call_list_written"] = len(call_list) - 1

    return stats
