"""Prospect CRUD + ranking. No HTTP concerns here — routers/tasks call these.

Agent 1 (Prospector) lands here via upsert_from_places(); Agent 2 (Researcher)
lands here via mark_research_*(); the operator lands here via list_prospects()
and set_outreach_status().
"""

import csv
import io
import math
import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.models.call import Call
from backend.models.prospect import Prospect
from backend.schemas.prospect import CompanyResearch, CsvImportResult

settings = get_settings()


def compute_priority(
    rating: float | None, review_count: int, website: str | None, phone: str | None
) -> float:
    """Transparent, weighted score — see config.py for the weights. Deliberately
    simple (no ML) so it's easy to explain and retune once real call outcomes exist.
    """
    rating_component = (rating or 0) / 5.0 * settings.priority_weight_rating
    reviews_component = math.log10(1 + max(review_count, 0)) * settings.priority_weight_reviews
    website_component = settings.priority_weight_website if website else 0.0
    phone_component = settings.priority_weight_phone if phone else 0.0
    return round(rating_component + reviews_component + website_component + phone_component, 4)


# The only verticals we actually sell into. Google's `primaryTypeDisplayName` and the
# CSV `niche` column are both free text, so historically every stray discovery run left
# its own bucket behind ("Dental Clinic", "British Restaurant", "Services", ...) and the
# operator's category filter turned into a junk drawer. Everything that isn't one of
# these collapses to NULL, which the UI already renders as "Unspecified" — the row is
# kept, only its label is dropped, so nothing is lost if we add a vertical later.
CANONICAL_CATEGORIES = ("Roofing", "Solar")

# Substring match on the lowercased raw value: Google says "Roofing Contractor",
# operators type "roofer"/"roofing", and solar shows up as "Solar Energy Contractor" or
# "photovoltaic". Order matters only in that the first hit wins.
_CATEGORY_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("roof", "Roofing"),
    ("solar", "Solar"),
    ("photovoltaic", "Solar"),
)


def normalize_category(raw: str | None) -> str | None:
    """Map a free-text category onto one of CANONICAL_CATEGORIES, or None."""
    if not raw:
        return None
    lowered = raw.lower()
    for keyword, canonical in _CATEGORY_KEYWORDS:
        if keyword in lowered:
            return canonical
    return None


async def upsert_from_places(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    places: list[dict],
    source_query: str,
    source_location: str | None = None,
) -> list[Prospect]:
    """Insert new prospects, update identity fields (+ re-score) on ones we've already
    seen, keyed by (tenant_id, google_place_id). Never touches research/outreach state
    on an existing row — discovery shouldn't clobber work Agent 2 or the operator did.

    `source_location` records the *where* of the search that found each row, and like
    `source_query` is written only on insert: re-running a different search that happens
    to return an already-known place shouldn't rewrite which search originally found it.
    """
    result = []
    for place in places:
        place_id = place.get("google_place_id")
        if not place_id:
            continue

        existing = await db.execute(
            select(Prospect).where(
                Prospect.tenant_id == tenant_id, Prospect.google_place_id == place_id
            )
        )
        prospect = existing.scalar_one_or_none()
        priority = compute_priority(
            place.get("rating"),
            place.get("review_count", 0),
            place.get("website"),
            place.get("phone"),
        )

        if prospect:
            prospect.name = place.get("name") or prospect.name
            prospect.website = place.get("website") or prospect.website
            prospect.phone = place.get("phone") or prospect.phone
            prospect.address = place.get("address") or prospect.address
            prospect.city = place.get("city") or prospect.city
            prospect.country = place.get("country") or prospect.country
            prospect.category = normalize_category(place.get("category")) or prospect.category
            prospect.rating = place.get("rating")
            prospect.review_count = place.get("review_count", 0)
            prospect.priority_score = priority
        else:
            prospect = Prospect(
                tenant_id=tenant_id,
                google_place_id=place_id,
                name=place.get("name") or "Unknown",
                website=place.get("website"),
                phone=place.get("phone"),
                address=place.get("address"),
                city=place.get("city"),
                country=place.get("country"),
                category=normalize_category(place.get("category")),
                rating=place.get("rating"),
                review_count=place.get("review_count", 0),
                source_query=source_query,
                source_location=source_location,
                priority_score=priority,
            )
            db.add(prospect)

        result.append(prospect)

    await db.commit()
    for prospect in result:
        await db.refresh(prospect)
    return result


class CsvImportError(Exception):
    """The file itself is unusable (wrong headers, too many rows) — as opposed to
    individual rows being bad, which CsvImportResult reports without failing.
    """


CSV_REQUIRED_COLUMNS = ("business_name", "phone")
CSV_OPTIONAL_COLUMNS = ("city", "country", "source", "niche", "website", "address")
CSV_MAX_ROWS = 5_000  # arbitrary sanity bound — an operator list, not a bulk data pipe
CSV_MAX_REPORTED_ERRORS = 20  # keep the response readable; counts stay exact

# Deliberately loose: strip formatting, then require an optional "+" and 7-15 digits
# (E.164's own bound). This is a first-pass sanity check to keep obvious junk out of the
# dialer, NOT real number validation — that needs a library with country metadata
# (phonenumbers) and a decision about default region, neither of which exists here yet.
_PHONE_STRIP_RE = re.compile(r"[\s\-().]")
_PHONE_RE = re.compile(r"^\+?\d{7,15}$")


def _cell(row: dict[str, str | None], name: str) -> str:
    return (row.get(name) or "").strip()


# Header spellings that mean one of our columns but don't normalize to its name. Kept
# small and explicit rather than fuzzy-matched: a wrong guess here silently imports a
# column into the wrong field, which is far worse than an "unknown column" skip. These
# are the spellings the operator's own lists and Retell's batch-call template use.
CSV_HEADER_ALIASES = {
    "phone_number": "phone",
    "phone_no": "phone",
    "telephone": "phone",
    "company_name": "business_name",
    "company": "business_name",
    "name": "business_name",
    "business": "business_name",
    "url": "website",
    "web": "website",
    "category": "niche",
}


def _normalize_header(h: str | None) -> str:
    """Casing/spacing/punctuation in a CSV's header row is an artifact of whatever
    exported it (Excel, Google Sheets, a scraper) — "Business Name" and "business_name"
    are the same column. Collapse both to the snake_case form CSV_REQUIRED_COLUMNS /
    CSV_OPTIONAL_COLUMNS and every _cell() lookup below expect, then map the known
    synonyms (CSV_HEADER_ALIASES) onto those names — "phone number" and "company_name"
    are what real scraped lists actually carry, and rejecting them as "missing required
    column" made the importer useless for exactly the files it exists to load.
    """
    normalized = re.sub(r"[^a-z0-9]+", "_", (h or "").strip().lower()).strip("_")
    return CSV_HEADER_ALIASES.get(normalized, normalized)


def normalize_website(raw: str | None) -> str | None:
    """Make an operator-typed website fetchable, or return None.

    research_service._fetch_website_text() hands the value straight to httpx.get(), which
    rejects a scheme-less "acme.com" outright — and that failure is swallowed into silent
    name-only research, so a whole column of bare domains would degrade every brief with
    nothing in the import report to show for it. Adding the scheme here is the difference
    between "no website" and "website we couldn't use". Deliberately not real URL
    validation: anything still unreachable at research time degrades as it always has.
    """
    if not raw:
        return None
    candidate = raw.strip()
    if not candidate:
        return None
    if not candidate.startswith(("http://", "https://")):
        candidate = f"https://{candidate}"
    return candidate


def normalize_phone(raw: str | None) -> str | None:
    """Formatting-insensitive form used for validation and storage. None if unusable.

    Strips spacing/punctuation only — it does NOT reconcile E.164 against national
    format, so "+442077335265" and "020 7733 5265" (the same London line) come back as
    two different strings. Use phone_match_key() for dedupe and cross-source matching;
    this is the wrong function for that and produced duplicate prospect rows when it was
    used for it.
    """
    if not raw:
        return None
    candidate = _PHONE_STRIP_RE.sub("", raw.strip())
    return candidate if _PHONE_RE.match(candidate) else None


def phone_match_key(raw: str | None) -> str | None:
    """A loose identity for a phone number — for dedupe and matching a call back to a
    prospect, NOT for storage or validation (that's normalize_phone).

    Reduces a number to its last 10 significant digits. That collapses the two ways the
    same line gets written down: strict E.164 ("+442077335265", what a voice platform
    reports) and national format with a trunk prefix ("020 7733 5265", what a scraped
    list often carries) — both end "2077335265". Ten digits because that is the
    significant-digit length of a NANP number and of a UK number past its country code:
    long enough that collisions within one tenant's prospect list are very unlikely,
    short enough to bridge the trunk-prefix gap.

    Deliberately not phonenumbers-library parsing — that needs a per-number region and a
    dependency this project has done without. If real lists ever throw false-positive
    collisions, that is the upgrade path.
    """
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if len(digits) < 7:  # below E.164's own lower bound — junk, not a number
        return None
    return digits[-10:]


async def import_from_csv(
    db: AsyncSession, tenant_id: uuid.UUID, content: str, source_query: str = "csv-import"
) -> CsvImportResult:
    """Create prospects from an operator-supplied CSV.

    Columns: business_name, phone (required); city, country, source, niche, website,
    address (optional). Header matching is case/spacing/punctuation-insensitive (see
    _normalize_header), so "Business Name" or "PHONE" both resolve fine — but the
    normalized form must still land on exactly these names (e.g. "Phone Number" would
    normalize to phone_number, not phone, and still be treated as missing). Rows with an
    unusable phone or no business_name are skipped and
    counted, not fatal. A missing website is NOT an invalid row — it just means that
    prospect gets degraded (name/address-only) research, which the result's
    with_website/without_website split reports up front.

    city and country are stored as their own columns (they drive the operator UI's
    grouping), and address additionally falls back to city when the richer `address`
    column is absent, so files written against the older header keep working; a full
    street address is preferred because research_service passes it to the LLM as a
    disambiguating signal.

    Dedupe is by normalized phone, within the tenant — both against rows already in the
    DB and against earlier rows in the same file, so re-uploading a list is a no-op
    rather than a duplicate set.
    """
    reader = csv.DictReader(io.StringIO(content))
    reader.fieldnames = [_normalize_header(h) for h in (reader.fieldnames or [])]
    headers = set(reader.fieldnames)
    missing = [c for c in CSV_REQUIRED_COLUMNS if c not in headers]
    if missing:
        raise CsvImportError(f"CSV is missing required column(s): {', '.join(missing)}")

    # One pass to build the dedupe set: stored phones keep their original formatting
    # (Places writes them verbatim, scraped lists vary), so they're reduced to a loose
    # match key here — phone_match_key, not normalize_phone, so a row already stored as
    # "+442077335265" blocks a re-import of the same line written "020 7733 5265".
    existing = await db.execute(
        select(Prospect.phone).where(Prospect.tenant_id == tenant_id, Prospect.phone.isnot(None))
    )
    seen_phones = {k for k in (phone_match_key(row) for row in existing.scalars()) if k}

    result = CsvImportResult()
    created: list[Prospect] = []

    def note(row_num: int, reason: str) -> None:
        if len(result.errors) < CSV_MAX_REPORTED_ERRORS:
            result.errors.append(f"row {row_num}: {reason}")

    for row_num, row in enumerate(reader, start=2):  # row 1 is the header
        if row_num - 1 > CSV_MAX_ROWS:
            raise CsvImportError(f"CSV exceeds the {CSV_MAX_ROWS}-row limit")

        name = _cell(row, "business_name")
        phone = normalize_phone(_cell(row, "phone"))

        if not name:
            result.skipped_invalid += 1
            note(row_num, "missing business_name")
            continue
        if not phone:
            result.skipped_invalid += 1
            note(row_num, f"unusable phone {_cell(row, 'phone')!r}")
            continue
        match_key = phone_match_key(phone)
        if match_key in seen_phones:
            result.skipped_duplicates += 1
            continue

        website = normalize_website(_cell(row, "website"))
        city = _cell(row, "city") or None
        # `city` now has its own column, but address still falls back to it: address is
        # what research_service passes to the scrape/LLM step as a disambiguating
        # signal, so dropping the fallback would silently degrade research for any file
        # that only carries a city. The two holding the same value is a fair price.
        address = _cell(row, "address") or city

        if match_key:
            seen_phones.add(match_key)
        prospect = Prospect(
            tenant_id=tenant_id,
            # Not from Places, but the column is NOT NULL and (tenant, place_id) is
            # the identity key the rest of the pipeline upserts on — keying it to the
            # phone keeps that key meaningful for CSV rows too.
            google_place_id=f"csv:{phone}",
            name=name,
            phone=phone,
            website=website,
            address=address,
            city=city,
            # Operator-typed and unvalidated, unlike the Places path's country, which
            # comes from Google's canonical addressComponents. Near-duplicate spellings
            # ("UK" vs "United Kingdom") will group separately in the UI — worth knowing
            # before blaming the grouping code.
            country=_cell(row, "country") or None,
            category=normalize_category(_cell(row, "niche")),
            source_query=_cell(row, "source") or source_query,
            # website is a scoring signal (see compute_priority), so a CSV row that
            # carries one should outrank one that doesn't, same as a Places row.
            priority_score=compute_priority(None, 0, website, phone),
        )
        db.add(prospect)
        created.append(prospect)

        result.imported += 1
        if website:
            result.with_website += 1
        else:
            result.without_website += 1

    await db.commit()
    # Ids exist only after the flush that commit() performs.
    result.imported_ids = [p.id for p in created]
    return result


async def list_prospects(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    research_status: str | None = None,
    outreach_status: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Prospect]:
    """One filtered page of the prospect list.

    `status` is the campaign-outcome axis, and it's what the dashboard's sections are
    built on: "not_called" is the work queue, "voicemail" the callback pile, "called" the
    ones a person actually spoke to. Comma-separated values are accepted so a section can
    span rungs (e.g. status=no_answer,voicemail) without needing its own endpoint.
    """
    query = select(Prospect).where(Prospect.tenant_id == tenant_id)
    if research_status:
        query = query.where(Prospect.research_status == research_status)
    if outreach_status:
        query = query.where(Prospect.outreach_status == outreach_status)
    if status:
        wanted = [s.strip() for s in status.split(",") if s.strip()]
        if wanted:
            query = query.where(Prospect.status.in_(wanted))
    query = query.order_by(Prospect.priority_score.desc()).limit(limit).offset(offset)

    result = await db.execute(query)
    return list(result.scalars().all())


async def count_by_status(db: AsyncSession, tenant_id: uuid.UUID) -> dict[str, int]:
    """Row counts per `status` for this tenant, plus a "total" key. A status with no
    rows is simply absent — the caller supplies the zeros (see schemas.ProspectStats).

    Aggregated in SQL rather than by counting a fetched page, so the numbers stay right
    past list_prospects()' default 100-row limit.
    """
    rows = await db.execute(
        select(Prospect.status, func.count())
        .where(Prospect.tenant_id == tenant_id)
        .group_by(Prospect.status)
    )
    counts = {status: count for status, count in rows.all()}
    counts["total"] = sum(counts.values())
    return counts


async def stale_research_prospects(db: AsyncSession, cutoff: datetime) -> list[Prospect]:
    """Prospects whose research has sat "pending" or "running" since before `cutoff` —
    the backstop for prospect_tasks.sweep_stale_prospects.

    `updated_at` is the right column for both states: for "pending" it's still the
    insertion time (nothing has touched the row since), and for "running" it's when
    mark_research_running() flipped it — so one comparison covers "never started" and
    "started but never finished" alike.

    Unscoped like get_prospect_unscoped: a Celery Beat sweep has no tenant to filter by
    and is meant to catch every stuck row across every tenant.
    """
    result = await db.execute(
        select(Prospect).where(
            Prospect.research_status.in_(["pending", "running"]),
            Prospect.updated_at < cutoff,
        )
    )
    return list(result.scalars().all())


async def get_prospect_unscoped(db: AsyncSession, prospect_id: uuid.UUID) -> Prospect | None:
    """Tenant-blind lookup — ONLY for trusted internal callers (Celery tasks acting on a
    prospect_id the system itself produced, and the mark_* helpers below).

    Never call this from a router: a prospect_id arriving over HTTP is attacker-controlled
    and must go through get_prospect() so ADR-001 isolation holds.
    """
    result = await db.execute(select(Prospect).where(Prospect.id == prospect_id))
    return result.scalar_one_or_none()


async def get_prospect(
    db: AsyncSession, prospect_id: uuid.UUID, tenant_id: uuid.UUID
) -> Prospect | None:
    """Fetch one prospect, scoped to its tenant (ADR-001). This is the router-facing
    lookup — another tenant's prospect reads as None so callers 404 rather than 403.
    """
    result = await db.execute(
        select(Prospect).where(Prospect.id == prospect_id, Prospect.tenant_id == tenant_id)
    )
    return result.scalar_one_or_none()


async def mark_research_running(db: AsyncSession, prospect_id: uuid.UUID) -> None:
    prospect = await get_prospect_unscoped(db, prospect_id)
    if not prospect:
        return
    prospect.research_status = "running"
    prospect.research_error = None
    await db.commit()


async def mark_research_ready(
    db: AsyncSession, prospect_id: uuid.UUID, research: CompanyResearch
) -> None:
    prospect = await get_prospect_unscoped(db, prospect_id)
    if not prospect:
        return
    prospect.research = research.model_dump()
    prospect.research_status = "ready"
    prospect.research_error = None
    await db.commit()


async def mark_research_failed(db: AsyncSession, prospect_id: uuid.UUID, error: str) -> None:
    prospect = await get_prospect_unscoped(db, prospect_id)
    if not prospect:
        return
    prospect.research_status = "failed"
    prospect.research_error = error
    await db.commit()


async def set_outreach_status(
    db: AsyncSession, prospect_id: uuid.UUID, tenant_id: uuid.UUID, status: str
) -> Prospect | None:
    prospect = await get_prospect(db, prospect_id, tenant_id)
    if not prospect:
        return None
    prospect.outreach_status = status
    await db.commit()
    await db.refresh(prospect)
    return prospect


async def set_status(
    db: AsyncSession, prospect_id: uuid.UUID, tenant_id: uuid.UUID, status: str
) -> Prospect | None:
    """Set the operator-facing campaign-outcome axis. Deliberately independent of
    set_outreach_status() — see the axes note in backend/models/prospect.py.
    """
    prospect = await get_prospect(db, prospect_id, tenant_id)
    if not prospect:
        return None
    prospect.status = status
    await db.commit()
    await db.refresh(prospect)
    return prospect


async def set_notes(
    db: AsyncSession, prospect_id: uuid.UUID, tenant_id: uuid.UUID, notes: str | None
) -> Prospect | None:
    """Set (or clear, with None/blank) the operator's hand-written context. Blank
    normalizes to None so "no notes" has one representation rather than two.
    """
    prospect = await get_prospect(db, prospect_id, tenant_id)
    if not prospect:
        return None
    prospect.prospect_notes = (notes or "").strip() or None
    await db.commit()
    await db.refresh(prospect)
    return prospect


async def record_call(db: AsyncSession, prospect_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    prospect = await get_prospect(db, prospect_id, tenant_id)
    if not prospect:
        return
    prospect.call_count += 1
    prospect.last_called_at = datetime.now(UTC)
    # "callback" is consumed here, not just advanced past: it's a one-shot request for a
    # retry (see batch_call_targets), and leaving it set would keep the prospect
    # permanently eligible and re-dial them on every subsequent batch run.
    if prospect.outreach_status in ("not_reached", "callback"):
        prospect.outreach_status = "reached"
    await db.commit()


# Forward-only ranking of the campaign-outcome axis, used by classify_call_outcome. A
# later, richer webhook can move a prospect *up* this ladder (a call_ended with nobody
# on the line, then a call_analyzed showing a human + negative sentiment), never back
# down — and a status not on the ladder at all (booked / do_not_call, both
# operator-set) is never touched. "flagged" IS on the ladder: it's the terminal
# auto-outcome for "a person rejected us", above a plain "called".
#
# "voicemail" sits above "no_answer" because it carries strictly more information: the
# line is live and an answering machine picked up, versus a phone that just rang out.
# That distinction is the operator's main retry signal — a voicemail number is worth
# calling back at a different hour, a dial_no_answer number may simply be dead — so it
# gets its own rung and its own dashboard section rather than being collapsed into one
# "we didn't reach anybody" bucket.
_OUTCOME_STATUS_ORDER = {
    "not_called": 0,
    "no_answer": 1,
    "voicemail": 2,
    "called": 3,
    "flagged": 4,
}

# Retell disconnection_reasons meaning "a machine, not a person, took the call".
_VOICEMAIL_REASONS = {"voicemail_reached", "machine_detected"}


def outcome_status_for_call(call: Call) -> str:
    """How one terminal call maps onto the campaign-outcome axis. Pure, so the
    single-call path (classify_call_outcome) and the whole-history path
    (resync_status_from_calls) can never disagree about what a call means.

    "Rejected" = a human was actually on the line AND Retell's post-call sentiment came
    back negative. Sentiment on a call nobody answered (or a 3-second hangup) is noise,
    so answered_by_human gates it. A sharper transcript-based signal can replace the
    sentiment check later without touching this seam.
    """
    if (call.disconnection_reason or "").lower() in _VOICEMAIL_REASONS:
        # Checked FIRST, ahead of answered_by_human, and that order is load-bearing.
        # answered_by_human is a heuristic — "did any transcript turn come from the far
        # end" — and an answering machine's outgoing greeting is transcribed as exactly
        # such a turn. So every voicemail looks like a human who talked, and testing
        # answered_by_human first classified a whole campaign of voicemails as "called".
        # Retell's own voicemail_reached verdict comes from its machine detection and is
        # authoritative about who picked up; our transcript heuristic is not.
        new_status = "voicemail"
    elif call.answered_by_human:
        rejected = call.sentiment_score is not None and call.sentiment_score <= 0.0
        new_status = "flagged" if rejected else "called"
    else:
        # dial_no_answer, user_declined, dial_busy/failed, or a "resolved" call with zero
        # caller turns — all "the phone rang and nothing picked up".
        new_status = "no_answer"

    return new_status


async def classify_call_outcome(db: AsyncSession, call: Call) -> None:
    """Advance Prospect.status off how a just-terminal prospect call ended. The prospect
    counterpart to lead_service.evaluate_call_outcome — called from
    call_service._fanout_post_call for any Call carrying a prospect_id.

    Idempotent by construction: it fires on call_ended, call_analyzed and any later
    reconcile, and only ever moves status forward along
    not_called -> no_answer -> voicemail -> called -> flagged (see _OUTCOME_STATUS_ORDER).
    A prospect an operator has already set to booked / do_not_call is left alone.

    Forward-only because this path sees ONE call at a time and can be handed a stale or
    partial view of it (a call_ended before call_analyzed has filled in sentiment). When
    the whole call history is available instead, resync_status_from_calls is the better
    authority and is allowed to move status down.
    """
    if not call.prospect_id:
        return
    prospect = await get_prospect_unscoped(db, call.prospect_id)
    if not prospect or prospect.status not in _OUTCOME_STATUS_ORDER:
        return

    new_status = outcome_status_for_call(call)
    if _OUTCOME_STATUS_ORDER[new_status] <= _OUTCOME_STATUS_ORDER[prospect.status]:
        return

    prospect.status = new_status
    if new_status in ("called", "flagged") and prospect.outreach_status == "not_reached":
        prospect.outreach_status = "reached"
    await db.commit()


async def resync_status_from_calls(db: AsyncSession, prospect: Prospect, calls: list[Call]) -> None:
    """Recompute Prospect.status from that prospect's ENTIRE call history.

    The whole-history counterpart to classify_call_outcome, and deliberately *not*
    forward-only: with every call in hand there is no ordering to protect against, so
    this is free to correct a status that the single-call path got wrong. That matters
    because the ladder is a ratchet — when voicemail detection was fixed, every prospect
    already stuck at "called" would have stayed there forever without a path that can
    move a status down.

    Status is the best outcome across all attempts (highest _OUTCOME_STATUS_ORDER rank),
    not the latest: a prospect who spoke to us in June and hit voicemail in August has
    still been reached, and burying that under the most recent attempt would lose the
    only fact the operator cares about. Operator-set statuses (booked, do_not_call) are
    off the ladder and never touched. Caller commits.
    """
    if prospect.status not in _OUTCOME_STATUS_ORDER:
        return

    best = "not_called"
    for call in calls:
        # Only terminal calls say anything; an in_progress row has no outcome yet.
        if call.status not in ("resolved", "escalated", "failed"):
            continue
        candidate = outcome_status_for_call(call)
        if _OUTCOME_STATUS_ORDER[candidate] > _OUTCOME_STATUS_ORDER[best]:
            best = candidate

    prospect.status = best
    if best in ("called", "flagged") and prospect.outreach_status == "not_reached":
        prospect.outreach_status = "reached"


# batch outreach + CSV export -------------------------------------------------------

BATCH_CALL_MAX = 50  # one dispatch loop, capped so a fat-fingered limit can't drain credit


async def batch_call_targets(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    limit: int,
    city: str | None = None,
    max_call_count: int = 0,
) -> list[Prospect]:
    """Prospects eligible for a batch outreach run: has a phone, not opted out, and
    either called no more than `max_call_count` times (0 = never called) **or** explicitly
    flagged for a callback. Highest priority first, so a truncated run works the best leads.

    The callback escape hatch is what makes "call this one again" possible at all: a
    prospect who has already been dialled three times and went to voicemail fails the
    `call_count <= max_call_count` test forever, which is correct as a default and wrong
    the moment an operator deliberately asks for a retry. `outreach_status == "callback"`
    is that ask — set from the sheet's "Call again?" column (sheets_service) or by hand
    via PATCH — and record_call() clears it back to "reached" as the call goes out, so
    one tick buys exactly one retry rather than a permanent re-dial loop.
    """
    query = select(Prospect).where(
        Prospect.tenant_id == tenant_id,
        Prospect.phone.isnot(None),
        or_(
            Prospect.call_count <= max_call_count,
            Prospect.outreach_status == "callback",
        ),
        Prospect.status.notin_(["do_not_call", "booked"]),
        Prospect.outreach_status != "do_not_call",
    )
    if city:
        query = query.where(Prospect.city == city)
    query = query.order_by(Prospect.priority_score.desc()).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


CSV_EXPORT_COLUMNS = (
    "phone number",
    "business_name",
    "website",
    "address",
    "city",
    "rating",
    "reviews",
    "status",
    "outreach_status",
    "call_count",
    "last_called_at",
)


async def export_csv(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    status: str | None = None,
    outreach_status: str | None = None,
    city: str | None = None,
) -> str:
    """Render the prospect list (optionally filtered) as CSV text. `phone number` is the
    first column so the file re-uploads straight into a Retell batch call; the trailing
    status columns are the outreach ledger classify_call_outcome maintains.
    """
    query = select(Prospect).where(Prospect.tenant_id == tenant_id)
    if status:
        query = query.where(Prospect.status == status)
    if outreach_status:
        query = query.where(Prospect.outreach_status == outreach_status)
    if city:
        query = query.where(Prospect.city == city)
    query = query.order_by(Prospect.priority_score.desc())
    rows = (await db.execute(query)).scalars().all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_EXPORT_COLUMNS)
    for p in rows:
        writer.writerow(
            [
                p.phone or "",
                p.name,
                p.website or "",
                p.address or "",
                p.city or "",
                p.rating if p.rating is not None else "",
                p.review_count,
                p.status,
                p.outreach_status,
                p.call_count,
                p.last_called_at.isoformat() if p.last_called_at else "",
            ]
        )
    return buf.getvalue()
