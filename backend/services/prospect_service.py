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

from sqlalchemy import func, select
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
            prospect.category = place.get("category") or prospect.category
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
                category=place.get("category"),
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


def _normalize_header(h: str | None) -> str:
    """Casing/spacing/punctuation in a CSV's header row is an artifact of whatever
    exported it (Excel, Google Sheets, a scraper) — "Business Name" and "business_name"
    are the same column. Collapse both to the snake_case form CSV_REQUIRED_COLUMNS /
    CSV_OPTIONAL_COLUMNS and every _cell() lookup below expect.
    """
    return re.sub(r"[^a-z0-9]+", "_", (h or "").strip().lower()).strip("_")


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
    """Formatting-insensitive form used both to validate and to dedupe. None if unusable."""
    if not raw:
        return None
    candidate = _PHONE_STRIP_RE.sub("", raw.strip())
    return candidate if _PHONE_RE.match(candidate) else None


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
    # (Places writes them verbatim), so they have to be normalized here to compare.
    existing = await db.execute(
        select(Prospect.phone).where(Prospect.tenant_id == tenant_id, Prospect.phone.isnot(None))
    )
    seen_phones = {p for p in (normalize_phone(row) for row in existing.scalars()) if p}

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
        if phone in seen_phones:
            result.skipped_duplicates += 1
            continue

        website = normalize_website(_cell(row, "website"))
        city = _cell(row, "city") or None
        # `city` now has its own column, but address still falls back to it: address is
        # what research_service passes to the scrape/LLM step as a disambiguating
        # signal, so dropping the fallback would silently degrade research for any file
        # that only carries a city. The two holding the same value is a fair price.
        address = _cell(row, "address") or city

        seen_phones.add(phone)
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
            category=_cell(row, "niche") or None,
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
    limit: int = 100,
    offset: int = 0,
) -> list[Prospect]:
    query = select(Prospect).where(Prospect.tenant_id == tenant_id)
    if research_status:
        query = query.where(Prospect.research_status == research_status)
    if outreach_status:
        query = query.where(Prospect.outreach_status == outreach_status)
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
    if prospect.outreach_status == "not_reached":
        prospect.outreach_status = "reached"
    await db.commit()


# Forward-only ranking of the campaign-outcome axis, used by classify_call_outcome. A
# later, richer webhook can move a prospect *up* this ladder (a call_ended with nobody
# on the line, then a call_analyzed showing a human + negative sentiment), never back
# down — and a status not on the ladder at all (booked / flagged / do_not_call, all
# operator-set) is never touched. "flagged" IS on the ladder: it's the terminal
# auto-outcome for "a person rejected us", above a plain "called".
_OUTCOME_STATUS_ORDER = {"not_called": 0, "no_answer": 1, "called": 2, "flagged": 3}


async def classify_call_outcome(db: AsyncSession, call: Call) -> None:
    """Advance Prospect.status off how a just-terminal prospect call ended. The prospect
    counterpart to lead_service.evaluate_call_outcome — called from
    call_service._fanout_post_call for any Call carrying a prospect_id.

    Idempotent by construction: it fires on call_ended, call_analyzed and any later
    reconcile, and only ever moves status forward along
    not_called -> no_answer -> called -> flagged (see _OUTCOME_STATUS_ORDER). A prospect
    an operator has already set to booked / flagged / do_not_call is left alone.

    "Rejected" = a human was actually on the line AND Retell's post-call sentiment came
    back negative. Sentiment on a call nobody answered (or a 3-second hangup) is noise,
    so answered_by_human gates it. A sharper transcript-based signal can replace the
    sentiment check later without touching this seam.
    """
    if not call.prospect_id:
        return
    prospect = await get_prospect_unscoped(db, call.prospect_id)
    if not prospect or prospect.status not in _OUTCOME_STATUS_ORDER:
        return

    if call.answered_by_human:
        rejected = call.sentiment_score is not None and call.sentiment_score <= 0.0
        new_status = "flagged" if rejected else "called"
    else:
        # voicemail_reached, dial_no_answer, user_declined, dial_busy/failed, or a
        # "resolved" call with zero caller turns — all "we didn't reach a person".
        new_status = "no_answer"

    if _OUTCOME_STATUS_ORDER[new_status] <= _OUTCOME_STATUS_ORDER[prospect.status]:
        return

    prospect.status = new_status
    if call.answered_by_human and prospect.outreach_status == "not_reached":
        prospect.outreach_status = "reached"
    await db.commit()


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
    called no more than `max_call_count` times (0 = never called). Highest priority
    first, so a truncated run works the best leads.
    """
    query = select(Prospect).where(
        Prospect.tenant_id == tenant_id,
        Prospect.phone.isnot(None),
        Prospect.call_count <= max_call_count,
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
