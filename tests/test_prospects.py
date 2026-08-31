"""Tests for the /api/prospects HTTP surface.

Service-level prospect logic (ranking, upsert-dedupe, research transitions) lives in
tests/test_prospect_service.py — this file covers the router: validation, tenant
scoping, and response shape.
"""

import uuid

import pytest

from backend.schemas.prospect import CompanyResearch
from backend.services import prospect_service, research_service
from backend.workers import prospect_tasks


def _session_factory(session):
    """Stand-in for prospect_tasks.AsyncSessionLocal that hands back the test session.

    The worker opens its own sessions (`async with AsyncSessionLocal() as db`) because it
    has no HTTP request to borrow one from, so exercising the real task body means
    substituting the factory. __aexit__ deliberately does not close: the fixture owns the
    session's lifetime, and _research() opens the factory three times in one run.
    """

    class _Factory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return session

        async def __aexit__(self, *exc_info):
            return False

    return _Factory()


async def _make_prospect(db_session, tenant_id, name="Acme HVAC", place_id="p_api"):
    [prospect] = await prospect_service.upsert_from_places(
        db_session, tenant_id, [{"google_place_id": place_id, "name": name}], "q"
    )
    return prospect


CSV_HEADER = "business_name,phone,city,source,niche\n"
CSV_HEADER_FULL = "business_name,phone,city,source,niche,website,address\n"


def _upload(content: str) -> dict:
    return {"file": ("prospects.csv", content.encode("utf-8"), "text/csv")}


@pytest.mark.asyncio
async def test_new_prospect_defaults_to_not_called(db_session, tenant_id):
    prospect = await _make_prospect(db_session, tenant_id)
    assert prospect.status == "not_called"


@pytest.mark.asyncio
async def test_patch_sets_status(client, db_session, tenant_id, auth_headers):
    prospect = await _make_prospect(db_session, tenant_id)

    resp = await client.patch(
        f"/api/prospects/{prospect.id}", json={"status": "booked"}, headers=auth_headers
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "booked"


@pytest.mark.asyncio
async def test_patch_rejects_unknown_status(client, db_session, tenant_id, auth_headers):
    prospect = await _make_prospect(db_session, tenant_id)

    resp = await client.patch(
        f"/api/prospects/{prospect.id}", json={"status": "vibing"}, headers=auth_headers
    )

    assert resp.status_code == 422
    assert "vibing" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_patch_status_does_not_touch_outreach_status(
    client, db_session, tenant_id, auth_headers
):
    """The two axes are independent by design (backend/models/prospect.py) — setting one
    must not silently advance the other.
    """
    prospect = await _make_prospect(db_session, tenant_id)

    resp = await client.patch(
        f"/api/prospects/{prospect.id}", json={"status": "no_answer"}, headers=auth_headers
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "no_answer"
    assert body["outreach_status"] == "not_reached"


@pytest.mark.asyncio
async def test_patch_can_set_both_axes_at_once(client, db_session, tenant_id, auth_headers):
    prospect = await _make_prospect(db_session, tenant_id)

    resp = await client.patch(
        f"/api/prospects/{prospect.id}",
        json={"status": "booked", "outreach_status": "reached"},
        headers=auth_headers,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "booked"
    assert body["outreach_status"] == "reached"


@pytest.mark.asyncio
async def test_patch_status_is_tenant_scoped(
    client, db_session, other_tenant_id, other_auth_headers
):
    """Another tenant's prospect must 404, not be silently updated (ADR-001)."""
    prospect = await _make_prospect(db_session, uuid.uuid4())

    resp = await client.patch(
        f"/api/prospects/{prospect.id}", json={"status": "booked"}, headers=other_auth_headers
    )

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_set_status_rejects_other_tenant(db_session, tenant_id, other_tenant_id):
    prospect = await _make_prospect(db_session, tenant_id)

    result = await prospect_service.set_status(
        db_session, prospect.id, other_tenant_id, "do_not_call"
    )

    assert result is None
    unchanged = await prospect_service.get_prospect(db_session, prospect.id, tenant_id)
    assert unchanged.status == "not_called"


# --- counts strip ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_stats_counts_by_status(client, db_session, tenant_id, auth_headers):
    a = await _make_prospect(db_session, tenant_id, "A", "p_a")
    b = await _make_prospect(db_session, tenant_id, "B", "p_b")
    await _make_prospect(db_session, tenant_id, "C", "p_c")  # stays not_called

    await prospect_service.set_status(db_session, a.id, tenant_id, "booked")
    await prospect_service.set_status(db_session, b.id, tenant_id, "no_answer")

    resp = await client.get("/api/prospects/stats", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json() == {
        "total": 3,
        "not_called": 1,
        "called": 0,
        "booked": 1,
        "flagged": 0,
        "no_answer": 1,
        "voicemail": 0,
        "do_not_call": 0,
    }


@pytest.mark.asyncio
async def test_stats_is_empty_for_a_tenant_with_no_prospects(client, auth_headers):
    resp = await client.get("/api/prospects/stats", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_stats_does_not_count_other_tenants(
    client, db_session, tenant_id, other_tenant_id, auth_headers
):
    await _make_prospect(db_session, tenant_id, "Mine", "p_mine")
    await _make_prospect(db_session, other_tenant_id, "Theirs", "p_theirs")

    resp = await client.get("/api/prospects/stats", headers=auth_headers)

    assert resp.json()["total"] == 1


@pytest.mark.asyncio
async def test_stats_path_is_not_swallowed_by_the_uuid_route(client, auth_headers):
    """/stats is declared before /{prospect_id}; if that ordering ever flips, this
    returns 422 (bad UUID) instead of the counts.
    """
    resp = await client.get("/api/prospects/stats", headers=auth_headers)
    assert resp.status_code == 200


# --- city autocomplete -------------------------------------------------------------


@pytest.mark.asyncio
async def test_city_autocomplete_path_is_not_swallowed_by_the_uuid_route(client, auth_headers):
    """Same route-ordering trap as /stats and /import-csv — declared above
    /{prospect_id} so this doesn't 422 as an invalid UUID.
    """
    resp = await client.get(
        "/api/prospects/city-autocomplete",
        params={"input": "Br", "session_token": "s1"},
        headers=auth_headers,
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_city_autocomplete_returns_suggestions(client, auth_headers, monkeypatch):
    from backend.api import prospects as prospects_api

    async def fake_autocomplete(input_text, session_token, region_code=None):
        assert input_text == "Bri"
        assert session_token == "session-1"
        assert region_code is None
        return [{"place_id": "place_bristol", "label": "Bristol, United Kingdom"}]

    monkeypatch.setattr(prospects_api.places_service, "autocomplete_cities", fake_autocomplete)

    resp = await client.get(
        "/api/prospects/city-autocomplete",
        params={"input": "Bri", "session_token": "session-1"},
        headers=auth_headers,
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "suggestions": [{"place_id": "place_bristol", "label": "Bristol, United Kingdom"}]
    }


@pytest.mark.asyncio
async def test_city_autocomplete_rejects_short_input_without_calling_google(
    client, auth_headers, monkeypatch
):
    """Defense in depth beyond the frontend's debounce — a single keystroke must not
    bill a Google request, whether the guard is bypassed by a bug or a direct hit.
    """
    from backend.api import prospects as prospects_api

    called = False

    async def fake_autocomplete(*args, **kwargs):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(prospects_api.places_service, "autocomplete_cities", fake_autocomplete)

    resp = await client.get(
        "/api/prospects/city-autocomplete",
        params={"input": "B", "session_token": "s1"},
        headers=auth_headers,
    )

    assert resp.status_code == 200
    assert resp.json() == {"suggestions": []}
    assert called is False


# --- CSV import ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+491701234567", "+491701234567"),
        ("+49 (170) 123-4567", "+491701234567"),
        ("020 7946 0958", "02079460958"),
        ("555-1234", "5551234"),  # 7 digits is the floor, so this squeaks through
        ("555-123", None),  # one short
        ("not a phone", None),
        ("", None),
        (None, None),
        ("+4917012345678901234", None),  # past E.164's 15-digit ceiling
    ],
)
def test_normalize_phone(raw, expected):
    assert prospect_service.normalize_phone(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+442077335265", "2077335265"),  # UK E.164
        ("020 7733 5265", "2077335265"),  # ...same line, national format — must collide
        ("+14059146006", "4059146006"),  # NANP
        ("4059146006", "4059146006"),
        ("555-123", None),  # too short to be a number
        ("", None),
        (None, None),
    ],
)
def test_phone_match_key_bridges_e164_and_national(raw, expected):
    assert prospect_service.phone_match_key(raw) == expected


@pytest.mark.asyncio
async def test_import_csv_creates_prospects(client, db_session, tenant_id, auth_headers):
    content = CSV_HEADER + (
        "Acme HVAC,+491701234567,Berlin,cold-list,hvac\n"
        "Sunbeam Solar,+491709876543,Munich,cold-list,solar\n"
    )

    resp = await client.post(
        "/api/prospects/import-csv", files=_upload(content), headers=auth_headers
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "imported": 2,
        "skipped_duplicates": 0,
        "skipped_invalid": 0,
        "errors": [],
        "with_website": 0,  # this header has no website column at all
        "without_website": 2,
    }

    rows = await prospect_service.list_prospects(db_session, tenant_id)
    by_name = {p.name: p for p in rows}
    assert by_name["Acme HVAC"].phone == "+491701234567"
    assert by_name["Acme HVAC"].city == "Berlin"  # city -> its own column
    assert by_name["Acme HVAC"].address == "Berlin"  # ...and still the address fallback
    # niche -> category, but only for the verticals we sell into: "hvac" isn't one, so
    # it lands unlabelled ("Unspecified" in the UI) rather than minting its own bucket.
    assert by_name["Acme HVAC"].category is None
    assert by_name["Sunbeam Solar"].category == "Solar"
    assert by_name["Acme HVAC"].source_query == "cold-list"  # source -> source_query
    assert by_name["Acme HVAC"].status == "not_called"


@pytest.mark.asyncio
async def test_import_csv_skips_duplicate_phones(client, db_session, tenant_id, auth_headers):
    """Duplicates within the file and against rows already stored both count as skips,
    and formatting differences must not defeat the check.
    """
    first = CSV_HEADER + "Acme HVAC,+491701234567,Berlin,cold-list,hvac\n"
    await client.post("/api/prospects/import-csv", files=_upload(first), headers=auth_headers)

    second = CSV_HEADER + (
        "Acme HVAC Again,+49 (170) 123-4567,Berlin,cold-list,hvac\n"  # already stored
        "New Co,+491700000001,Berlin,cold-list,hvac\n"
        "New Co Dupe,+49 170 000 0001,Berlin,cold-list,hvac\n"  # repeat within this file
    )
    resp = await client.post(
        "/api/prospects/import-csv", files=_upload(second), headers=auth_headers
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["imported"] == 1
    assert body["skipped_duplicates"] == 2

    rows = await prospect_service.list_prospects(db_session, tenant_id)
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_import_csv_dedupes_e164_against_national_format(
    client, db_session, tenant_id, auth_headers
):
    """The bug that seeded 5 duplicate London roofers: a list carrying "+442077335265"
    and a later list carrying "020 7733 5265" are the same line and must not both import.
    """
    first = CSV_HEADER + "Dulwich Roofing,+442077335265,London,cold-list,roofing\n"
    await client.post("/api/prospects/import-csv", files=_upload(first), headers=auth_headers)

    second = CSV_HEADER + "Dulwich Roofing Ltd,020 7733 5265,London,cold-list,roofing\n"
    resp = await client.post(
        "/api/prospects/import-csv", files=_upload(second), headers=auth_headers
    )

    assert resp.json()["skipped_duplicates"] == 1
    assert resp.json()["imported"] == 0
    assert len(await prospect_service.list_prospects(db_session, tenant_id)) == 1


@pytest.mark.asyncio
async def test_import_csv_reports_invalid_rows_without_failing(client, tenant_id, auth_headers):
    content = CSV_HEADER + (
        "Good Co,+491701234567,Berlin,cold-list,hvac\n"
        "Bad Phone Co,banana,Berlin,cold-list,hvac\n"
        ",+491700000009,Berlin,cold-list,hvac\n"  # no business_name
    )

    resp = await client.post(
        "/api/prospects/import-csv", files=_upload(content), headers=auth_headers
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["imported"] == 1
    assert body["skipped_invalid"] == 2
    assert any("banana" in e for e in body["errors"])
    assert any("business_name" in e for e in body["errors"])


@pytest.mark.asyncio
async def test_import_csv_rejects_missing_required_columns(client, auth_headers):
    # "company"/"telephone" used to be the fixture here, but they are now recognized
    # aliases (CSV_HEADER_ALIASES) and import fine — which is the point of the aliases.
    # Headers that map to nothing at all are what this test is actually about.
    resp = await client.post(
        "/api/prospects/import-csv",
        files=_upload("org_label,contact_digits\nAcme,+491701234567\n"),
        headers=auth_headers,
    )

    assert resp.status_code == 422
    assert "business_name" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_import_csv_accepts_header_aliases(client, auth_headers):
    """The operator's real lists say "phone number" / "company_name", and Retell's batch
    template says "phone number" too — rejecting those made the importer useless for
    exactly the files it exists to load.
    """
    resp = await client.post(
        "/api/prospects/import-csv",
        files=_upload("company_name,phone number,url\nAcme Roofing,+491701234567,acme.test\n"),
        headers=auth_headers,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["imported"] == 1
    assert body["with_website"] == 1


@pytest.mark.asyncio
async def test_import_csv_tolerates_excel_bom(client, auth_headers):
    """Excel's "CSV UTF-8" export prepends a BOM, which would otherwise glue itself to
    the first header name and fail the required-column check.
    """
    content = "﻿" + CSV_HEADER + "Acme HVAC,+491701234567,Berlin,cold-list,hvac\n"

    resp = await client.post(
        "/api/prospects/import-csv", files=_upload(content), headers=auth_headers
    )

    assert resp.status_code == 200
    assert resp.json()["imported"] == 1


@pytest.mark.asyncio
async def test_import_csv_tolerates_header_casing_and_spacing(client, auth_headers):
    """Real-world exports (Excel, Google Sheets, scrapers) write "Business Name" /
    "Phone" rather than the snake_case the importer stores internally — headers should
    be matched loosely rather than forcing operators to hand-edit every file.
    """
    content = "Business Name,Phone,City\nAcme HVAC,+491701234567,Berlin\n"

    resp = await client.post(
        "/api/prospects/import-csv", files=_upload(content), headers=auth_headers
    )

    assert resp.status_code == 200
    assert resp.json()["imported"] == 1


@pytest.mark.asyncio
async def test_import_csv_is_tenant_scoped(
    client, db_session, tenant_id, other_tenant_id, auth_headers, other_auth_headers
):
    """The same phone in two tenants is not a duplicate — dedupe must not leak across
    the tenant boundary (ADR-001).
    """
    content = CSV_HEADER + "Acme HVAC,+491701234567,Berlin,cold-list,hvac\n"

    await client.post("/api/prospects/import-csv", files=_upload(content), headers=auth_headers)
    resp = await client.post(
        "/api/prospects/import-csv", files=_upload(content), headers=other_auth_headers
    )

    assert resp.status_code == 200
    assert resp.json()["imported"] == 1
    assert len(await prospect_service.list_prospects(db_session, tenant_id)) == 1
    assert len(await prospect_service.list_prospects(db_session, other_tenant_id)) == 1


# --- CSV import: website/address and the research handoff -------------------------


@pytest.mark.asyncio
async def test_import_csv_stores_website_and_address(client, db_session, tenant_id, auth_headers):
    """The richer `address` column wins over `city`, and a bare domain is made fetchable
    so research_service doesn't silently degrade the row to name-only research.
    """
    content = CSV_HEADER_FULL + (
        "Acme HVAC,+491701234567,Berlin,cold-list,hvac,https://acme-hvac.de,Hauptstr. 5 Berlin\n"
        "Sunbeam Solar,+491709876543,Munich,cold-list,solar,sunbeam.example,\n"
    )

    resp = await client.post(
        "/api/prospects/import-csv", files=_upload(content), headers=auth_headers
    )

    assert resp.status_code == 200
    rows = {p.name: p for p in await prospect_service.list_prospects(db_session, tenant_id)}
    assert rows["Acme HVAC"].website == "https://acme-hvac.de"
    assert rows["Acme HVAC"].address == "Hauptstr. 5 Berlin"  # address beats city
    assert rows["Sunbeam Solar"].website == "https://sunbeam.example"  # scheme added
    assert rows["Sunbeam Solar"].address == "Munich"  # falls back to city

    # city keeps its own value either way — a richer address must not cost us the city.
    assert rows["Acme HVAC"].city == "Berlin"
    assert rows["Sunbeam Solar"].city == "Munich"


@pytest.mark.asyncio
async def test_import_csv_stores_country(client, db_session, tenant_id, auth_headers):
    """Without this, every CSV row groups under "Unknown country" forever. Unlike the
    Places path this value is operator-typed and unvalidated — stored verbatim.
    """
    content = "business_name,phone,city,country\n" + (
        "Acme HVAC,+491701234567,Berlin,Germany\nBristol Solar,+441172510125,Bristol,\n"
    )

    resp = await client.post(
        "/api/prospects/import-csv", files=_upload(content), headers=auth_headers
    )

    assert resp.status_code == 200
    rows = {p.name: p for p in await prospect_service.list_prospects(db_session, tenant_id)}
    assert rows["Acme HVAC"].country == "Germany"
    assert rows["Bristol Solar"].country is None  # blank stays null, not ""


@pytest.mark.asyncio
async def test_import_csv_without_a_country_column_still_works(
    client, db_session, tenant_id, auth_headers
):
    """country is optional — files written against the older header must keep importing."""
    content = CSV_HEADER + "Acme HVAC,+491701234567,Berlin,cold-list,hvac\n"

    resp = await client.post(
        "/api/prospects/import-csv", files=_upload(content), headers=auth_headers
    )

    assert resp.status_code == 200
    [prospect] = await prospect_service.list_prospects(db_session, tenant_id)
    assert prospect.country is None
    assert prospect.city == "Berlin"


@pytest.mark.asyncio
async def test_import_csv_reports_website_coverage(client, auth_headers):
    """The operator needs the degraded-research count up front, not after the briefs
    come back thin.
    """
    content = CSV_HEADER_FULL + (
        "Has Site,+491701234567,Berlin,cold-list,hvac,https://a.example,Berlin\n"
        "No Site,+491709876543,Berlin,cold-list,hvac,,Berlin\n"
        "Blank Site,+491700000002,Berlin,cold-list,hvac,   ,Berlin\n"
    )

    resp = await client.post(
        "/api/prospects/import-csv", files=_upload(content), headers=auth_headers
    )

    body = resp.json()
    assert body["imported"] == 3
    assert body["with_website"] == 1
    assert body["without_website"] == 2
    assert body["with_website"] + body["without_website"] == body["imported"]
    assert "imported_ids" not in body  # internal handoff, not part of the report


@pytest.mark.asyncio
async def test_import_csv_enqueues_research_per_imported_row(
    client, db_session, tenant_id, auth_headers, queued_research
):
    """Same one-task-per-prospect enqueue discovery does — and skipped rows must not
    produce a task.
    """
    content = CSV_HEADER_FULL + (
        "Good Co,+491701234567,Berlin,cold-list,hvac,https://a.example,Berlin\n"
        "Bad Phone Co,banana,Berlin,cold-list,hvac,,Berlin\n"
    )

    resp = await client.post(
        "/api/prospects/import-csv", files=_upload(content), headers=auth_headers
    )

    assert resp.json()["imported"] == 1
    [prospect] = await prospect_service.list_prospects(db_session, tenant_id)
    assert queued_research == [str(prospect.id)]


@pytest.mark.asyncio
async def test_imported_prospect_reaches_research_ready_via_the_pipeline(
    client, db_session, tenant_id, auth_headers, queued_research, monkeypatch
):
    """End to end over the real Agent 2 body: import a row with website+address, then run
    the same prospect_tasks._research() coroutine the discovery chain runs, and confirm
    the row lands at research_status="ready" with the brief stored on it.

    research_company itself is stubbed — it is the one step that makes a live HTTP scrape
    and a paid DeepSeek call. Everything between the import and the stored result is the
    production path, including the arguments the pipeline hands it.
    """
    content = CSV_HEADER_FULL + (
        "Acme HVAC,+491701234567,Berlin,cold-list,hvac,https://acme-hvac.de,Hauptstr. 5 Berlin\n"
    )
    resp = await client.post(
        "/api/prospects/import-csv", files=_upload(content), headers=auth_headers
    )
    assert resp.json() == {
        "imported": 1,
        "skipped_duplicates": 0,
        "skipped_invalid": 0,
        "errors": [],
        "with_website": 1,
        "without_website": 0,
    }

    [prospect] = await prospect_service.list_prospects(db_session, tenant_id)
    assert prospect.research_status == "pending"
    assert queued_research == [str(prospect.id)]

    seen: dict[str, str | None] = {}

    async def fake_research_company(name, website, address):
        seen.update(name=name, website=website, address=address)
        return CompanyResearch(summary="Family-run HVAC installer", industry="HVAC")

    monkeypatch.setattr(research_service, "research_company", fake_research_company)
    monkeypatch.setattr(prospect_tasks, "AsyncSessionLocal", _session_factory(db_session))

    await prospect_tasks._research(queued_research[0])

    # The pipeline must pass through what the CSV supplied — a dropped website here is
    # exactly the silent degradation the with_website count exists to surface.
    assert seen == {
        "name": "Acme HVAC",
        "website": "https://acme-hvac.de",
        "address": "Hauptstr. 5 Berlin",
    }

    refreshed = await prospect_service.get_prospect(db_session, prospect.id, tenant_id)
    assert refreshed.research_status == "ready"
    assert refreshed.research_error is None
    assert refreshed.research["summary"] == "Family-run HVAC installer"


# --- prospect_notes --------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_prospect_has_no_notes(db_session, tenant_id):
    prospect = await _make_prospect(db_session, tenant_id)
    assert prospect.prospect_notes is None


@pytest.mark.asyncio
async def test_patch_sets_and_returns_notes(client, db_session, tenant_id, auth_headers):
    prospect = await _make_prospect(db_session, tenant_id)

    resp = await client.patch(
        f"/api/prospects/{prospect.id}",
        json={"prospect_notes": "Owner is Maria, only answers before 9am."},
        headers=auth_headers,
    )

    assert resp.status_code == 200
    assert resp.json()["prospect_notes"] == "Owner is Maria, only answers before 9am."


@pytest.mark.asyncio
async def test_patch_can_clear_notes(client, db_session, tenant_id, auth_headers):
    """An explicit null means "clear", which must not read as "field not supplied"."""
    prospect = await _make_prospect(db_session, tenant_id)
    await client.patch(
        f"/api/prospects/{prospect.id}", json={"prospect_notes": "temp"}, headers=auth_headers
    )

    resp = await client.patch(
        f"/api/prospects/{prospect.id}", json={"prospect_notes": None}, headers=auth_headers
    )

    assert resp.status_code == 200
    assert resp.json()["prospect_notes"] is None


@pytest.mark.asyncio
async def test_blank_notes_normalize_to_null(client, db_session, tenant_id, auth_headers):
    """One representation of "no notes", so build_prospect_prompt's blank check is the
    only place emptiness has to be reasoned about.
    """
    prospect = await _make_prospect(db_session, tenant_id)

    resp = await client.patch(
        f"/api/prospects/{prospect.id}", json={"prospect_notes": "   \n "}, headers=auth_headers
    )

    assert resp.json()["prospect_notes"] is None


@pytest.mark.asyncio
async def test_patch_notes_leaves_the_status_axes_alone(
    client, db_session, tenant_id, auth_headers
):
    prospect = await _make_prospect(db_session, tenant_id)
    await prospect_service.set_status(db_session, prospect.id, tenant_id, "booked")

    resp = await client.patch(
        f"/api/prospects/{prospect.id}", json={"prospect_notes": "note"}, headers=auth_headers
    )

    body = resp.json()
    assert body["prospect_notes"] == "note"
    assert body["status"] == "booked"
    assert body["outreach_status"] == "not_reached"


@pytest.mark.asyncio
async def test_patch_notes_is_tenant_scoped(client, db_session, other_auth_headers):
    prospect = await _make_prospect(db_session, uuid.uuid4())

    resp = await client.patch(
        f"/api/prospects/{prospect.id}", json={"prospect_notes": "leak"}, headers=other_auth_headers
    )

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_set_notes_rejects_other_tenant(db_session, tenant_id, other_tenant_id):
    prospect = await _make_prospect(db_session, tenant_id)

    result = await prospect_service.set_notes(db_session, prospect.id, other_tenant_id, "leak")

    assert result is None
    unchanged = await prospect_service.get_prospect(db_session, prospect.id, tenant_id)
    assert unchanged.prospect_notes is None


# --- personalized outbound call ---------------------------------------------------


@pytest.fixture
def placed_calls(monkeypatch) -> list[dict]:
    """Capture what would have been dialed instead of spending a real, billed call.

    Patched at backend.api.prospects.test_call_service so the router's own reference is
    the one replaced — everything up to the Retell boundary stays the production path,
    including prompt assembly, which is what these tests are actually about.
    """
    from backend.api import prospects as prospects_api

    calls: list[dict] = []

    async def fake_place_test_call(
        db, agent_id, tenant_id, to_number, system_prompt_override=None, prospect_id=None
    ):
        calls.append(
            {
                "agent_id": agent_id,
                "to_number": to_number,
                "prompt": system_prompt_override,
                "prospect_id": prospect_id,
            }
        )
        return {
            "call_id": f"mock_call_{len(calls)}",
            "from_number": "+10000000000",
            "status": "dialing",
        }

    monkeypatch.setattr(prospects_api.test_call_service, "place_test_call", fake_place_test_call)
    return calls


async def _researched_prospect(db_session, tenant_id, notes=None):
    prospect = await _make_prospect(db_session, tenant_id, "Acme HVAC", "p_call")
    prospect.phone = "+491701111111"
    await prospect_service.mark_research_ready(
        db_session,
        prospect.id,
        CompanyResearch(summary="Family-run HVAC installer", hooks=["New Berlin depot"]),
    )
    if notes is not None:
        await prospect_service.set_notes(db_session, prospect.id, tenant_id, notes)
    return await prospect_service.get_prospect(db_session, prospect.id, tenant_id)


async def _agent(db_session, tenant_id):
    from backend.schemas.agent import AgentCreate
    from backend.services import agent_service

    return await agent_service.create_agent(
        db_session,
        tenant_id,
        AgentCreate(name="SDR", system_prompt="[ROLE] You are Alex.", platform="retell"),
    )


@pytest.mark.asyncio
async def test_call_dials_the_prospects_own_number_by_default(
    client, db_session, tenant_id, auth_headers, placed_calls
):
    prospect = await _researched_prospect(db_session, tenant_id)
    agent = await _agent(db_session, tenant_id)

    resp = await client.post(
        f"/api/prospects/{prospect.id}/call",
        json={"agent_id": str(agent.id)},
        headers=auth_headers,
    )

    assert resp.status_code == 200
    assert placed_calls[0]["to_number"] == prospect.phone


@pytest.mark.asyncio
async def test_call_advances_outreach_counters(
    client, db_session, tenant_id, auth_headers, placed_calls
):
    prospect = await _researched_prospect(db_session, tenant_id)
    agent = await _agent(db_session, tenant_id)

    await client.post(
        f"/api/prospects/{prospect.id}/call",
        json={"agent_id": str(agent.id)},
        headers=auth_headers,
    )

    refreshed = await prospect_service.get_prospect(db_session, prospect.id, tenant_id)
    assert refreshed.call_count == 1
    assert refreshed.outreach_status == "reached"


@pytest.mark.asyncio
async def test_call_injects_research_and_notes(
    client, db_session, tenant_id, auth_headers, placed_calls
):
    """What the agent is told to say must carry the base script, the researched brief,
    and the operator's own notes — all three, assembled by build_prospect_prompt.
    """
    prospect = await _researched_prospect(
        db_session, tenant_id, notes="Owner is Maria, only answers before 9am."
    )
    agent = await _agent(db_session, tenant_id)

    await client.post(
        f"/api/prospects/{prospect.id}/call",
        json={"agent_id": str(agent.id)},
        headers=auth_headers,
    )

    prompt = placed_calls[0]["prompt"]
    assert "[ROLE] You are Alex." in prompt  # base script preserved
    assert "Family-run HVAC installer" in prompt  # research
    assert "New Berlin depot" in prompt  # research
    assert "Owner is Maria" in prompt  # operator notes


@pytest.mark.asyncio
async def test_call_requires_ready_research(
    client, db_session, tenant_id, auth_headers, placed_calls
):
    prospect = await _make_prospect(db_session, tenant_id)  # research_status stays "pending"
    agent = await _agent(db_session, tenant_id)

    resp = await client.post(
        f"/api/prospects/{prospect.id}/call",
        json={"agent_id": str(agent.id)},
        headers=auth_headers,
    )

    assert resp.status_code == 422
    assert placed_calls == []


@pytest.mark.asyncio
async def test_call_is_tenant_scoped(
    client, db_session, tenant_id, other_auth_headers, placed_calls
):
    prospect = await _researched_prospect(db_session, tenant_id)
    agent = await _agent(db_session, tenant_id)

    resp = await client.post(
        f"/api/prospects/{prospect.id}/call",
        json={"agent_id": str(agent.id)},
        headers=other_auth_headers,
    )

    assert resp.status_code == 404
    assert placed_calls == []


# --- calling a prospect with a platform-native agent (ADR-012) ----------------------


@pytest.fixture
def placed_platform_calls(monkeypatch) -> list[dict]:
    """Same capture idea as placed_calls, for the other dial source."""
    from backend.api import prospects as prospects_api

    calls: list[dict] = []

    async def fake_place(
        db, tenant_id, external_agent_id, to_number, dynamic_variables=None, prospect_id=None
    ):
        calls.append(
            {
                "external_agent_id": external_agent_id,
                "to_number": to_number,
                "dynamic_variables": dynamic_variables,
                "prospect_id": prospect_id,
            }
        )
        return {
            "call_id": f"mock_ext_call_{len(calls)}",
            "from_number": "+10000000000",
            "status": "dialing",
            "agent_name": "Roofing Agent Test Case #1",
        }

    monkeypatch.setattr(prospects_api.test_call_service, "place_platform_agent_call", fake_place)
    return calls


@pytest.mark.asyncio
async def test_call_with_a_platform_agent_sends_no_personalized_prompt(
    client, db_session, tenant_id, auth_headers, placed_calls, placed_platform_calls
):
    """The whole distinction: a dashboard-built agent holds its own script and there is
    no channel to hand it this prospect's brief. It must not silently take the
    personalized path instead."""
    prospect = await _researched_prospect(db_session, tenant_id, notes="Owner is Maria.")

    resp = await client.post(
        f"/api/prospects/{prospect.id}/call",
        json={"external_agent_id": "agent_ext_9"},
        headers=auth_headers,
    )

    assert resp.status_code == 200
    assert placed_calls == []  # the personalized path was not used
    assert placed_platform_calls == [
        {
            "external_agent_id": "agent_ext_9",
            "to_number": prospect.phone,
            "dynamic_variables": {},
            "prospect_id": prospect.id,
        }
    ]


@pytest.mark.asyncio
async def test_call_with_a_platform_agent_still_advances_outreach(
    client, db_session, tenant_id, auth_headers, placed_platform_calls
):
    """The prospect was still called, whichever agent did it."""
    prospect = await _researched_prospect(db_session, tenant_id)

    await client.post(
        f"/api/prospects/{prospect.id}/call",
        json={"external_agent_id": "agent_ext_9"},
        headers=auth_headers,
    )

    refreshed = await prospect_service.get_prospect(db_session, prospect.id, tenant_id)
    assert refreshed.call_count == 1
    assert refreshed.outreach_status == "reached"


@pytest.mark.asyncio
async def test_call_with_a_platform_agent_does_not_wait_for_research(
    client, db_session, tenant_id, auth_headers, placed_platform_calls
):
    """The ready-gate exists because the personalized prompt needs the [COMPANY BRIEF].
    With nothing to inject there is nothing to wait for — which is also what makes a
    CSV-imported prospect (never reaches "ready", ADR-006) callable at all."""
    prospect = await _make_prospect(db_session, tenant_id)  # research_status "pending"
    prospect.phone = "+491701111111"
    await db_session.commit()

    resp = await client.post(
        f"/api/prospects/{prospect.id}/call",
        json={"external_agent_id": "agent_ext_9"},
        headers=auth_headers,
    )

    assert resp.status_code == 200
    assert len(placed_platform_calls) == 1


@pytest.mark.asyncio
async def test_call_rejects_naming_both_or_neither_agent(
    client, db_session, tenant_id, auth_headers, placed_calls, placed_platform_calls
):
    """Neither leaves nobody to dial with; both makes it ambiguous which script runs —
    and the two differ in exactly the way this page is about."""
    prospect = await _researched_prospect(db_session, tenant_id)
    agent = await _agent(db_session, tenant_id)

    for body in (
        {},
        {"agent_id": str(agent.id), "external_agent_id": "agent_ext_9"},
    ):
        resp = await client.post(
            f"/api/prospects/{prospect.id}/call", json=body, headers=auth_headers
        )
        assert resp.status_code == 422, body

    assert placed_calls == []
    assert placed_platform_calls == []


@pytest.mark.asyncio
async def test_call_with_a_platform_agent_is_tenant_scoped(
    client, db_session, tenant_id, other_auth_headers, placed_platform_calls
):
    prospect = await _researched_prospect(db_session, tenant_id)

    resp = await client.post(
        f"/api/prospects/{prospect.id}/call",
        json={"external_agent_id": "agent_ext_9"},
        headers=other_auth_headers,
    )

    assert resp.status_code == 404
    assert placed_platform_calls == []


@pytest.mark.asyncio
async def test_call_forwards_dynamic_variables_to_the_platform_agent(
    client, db_session, tenant_id, auth_headers, placed_platform_calls
):
    """The only personalization channel a dashboard agent has: its prompt's own
    {{placeholders}}, filled per call. Without this the agent greets every prospect
    identically."""
    prospect = await _researched_prospect(db_session, tenant_id)

    await client.post(
        f"/api/prospects/{prospect.id}/call",
        json={
            "external_agent_id": "agent_ext_9",
            "dynamic_variables": {"company_name": "Acme HVAC", "contact_name": "Maria"},
        },
        headers=auth_headers,
    )

    assert placed_platform_calls[0]["dynamic_variables"] == {
        "company_name": "Acme HVAC",
        "contact_name": "Maria",
    }


@pytest.mark.asyncio
async def test_call_links_the_call_to_its_prospect(
    client, db_session, tenant_id, auth_headers, placed_calls
):
    """Without prospect_id on the Call row, the outcome webhook can't feed back."""
    prospect = await _researched_prospect(db_session, tenant_id)
    agent = await _agent(db_session, tenant_id)

    await client.post(
        f"/api/prospects/{prospect.id}/call",
        json={"agent_id": str(agent.id)},
        headers=auth_headers,
    )

    assert placed_calls[0]["prospect_id"] == prospect.id


# --- batch outbound calling ------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_call_dials_uncalled_prospects_and_reports(
    client, db_session, tenant_id, auth_headers, placed_platform_calls
):
    for i in range(3):
        p = await _make_prospect(db_session, tenant_id, f"Roofer {i}", f"p_batch_{i}")
        p.phone = f"+44117000000{i}"
    await db_session.commit()

    resp = await client.post(
        "/api/prospects/batch-call",
        json={"external_agent_id": "agent_ext_1", "limit": 2},
        headers=auth_headers,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["requested"] == 2
    assert len(body["dispatched"]) == 2
    assert len(placed_platform_calls) == 2
    # every dial carried its prospect_id
    assert all(c["prospect_id"] is not None for c in placed_platform_calls)


@pytest.mark.asyncio
async def test_batch_call_skips_prospects_without_ready_research_on_the_local_path(
    client, db_session, tenant_id, auth_headers, placed_calls
):
    ready = await _researched_prospect(db_session, tenant_id)
    not_ready = await _make_prospect(db_session, tenant_id, "Unresearched", "p_nr")
    not_ready.phone = "+441170009999"
    await db_session.commit()
    agent = await _agent(db_session, tenant_id)

    resp = await client.post(
        "/api/prospects/batch-call",
        json={"agent_id": str(agent.id), "limit": 10},
        headers=auth_headers,
    )

    body = resp.json()
    dispatched_names = [d["name"] for d in body["dispatched"]]
    skipped_names = [s["name"] for s in body["skipped"]]
    assert ready.name in dispatched_names
    assert not_ready.name in skipped_names
    assert len(placed_calls) == 1


@pytest.mark.asyncio
async def test_batch_call_rejects_naming_both_or_neither_agent(client, auth_headers):
    for body in ({}, {"agent_id": str(uuid.uuid4()), "external_agent_id": "x"}):
        resp = await client.post("/api/prospects/batch-call", json=body, headers=auth_headers)
        assert resp.status_code == 422


# --- CSV export -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_returns_csv_with_the_retell_phone_header(
    client, db_session, tenant_id, auth_headers
):
    p = await _make_prospect(db_session, tenant_id, "Exported Co", "p_exp")
    p.phone = "+441170001234"
    await db_session.commit()

    resp = await client.get("/api/prospects/export", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    lines = resp.text.splitlines()
    assert lines[0].split(",")[0] == "phone number"
    assert "Exported Co" in resp.text


# --- prospect sandbox chat ---------------------------------------------------------


@pytest.fixture
def chat_calls(monkeypatch) -> list[dict]:
    """Capture what would have been sent to the LLM, instead of spending a real,
    billed completion. Patched at llm_service.get_agent_response — the one function
    sandbox_service.chat() (and therefore the sandbox-chat route) ultimately calls.
    """
    from backend.services import llm_service

    calls: list[dict] = []

    async def fake_get_agent_response(
        system_prompt, messages, caller_context, *, model=None, tools_enabled=True, **kwargs
    ):
        calls.append(
            {
                "system_prompt": system_prompt,
                "messages": messages,
                "model": model,
                "tools_enabled": tools_enabled,
            }
        )
        return "Hi, thanks for calling!"

    monkeypatch.setattr(llm_service, "get_agent_response", fake_get_agent_response)
    return calls


@pytest.mark.asyncio
async def test_sandbox_chat_returns_a_reply(
    client, db_session, tenant_id, auth_headers, chat_calls
):
    prospect = await _researched_prospect(db_session, tenant_id)
    agent = await _agent(db_session, tenant_id)

    resp = await client.post(
        f"/api/prospects/{prospect.id}/sandbox-chat",
        json={"agent_id": str(agent.id), "messages": [{"role": "user", "content": "Hello"}]},
        headers=auth_headers,
    )

    assert resp.status_code == 200
    assert resp.json()["reply"] == "Hi, thanks for calling!"


@pytest.mark.asyncio
async def test_sandbox_chat_response_includes_the_prompt_actually_sent(
    client, db_session, tenant_id, auth_headers, chat_calls
):
    """The response should carry the exact prompt the LLM ran against, so a sandbox
    UI can show it verbatim instead of reconstructing an approximation client-side.
    """
    prospect = await _researched_prospect(db_session, tenant_id)
    agent = await _agent(db_session, tenant_id)

    resp = await client.post(
        f"/api/prospects/{prospect.id}/sandbox-chat",
        json={"agent_id": str(agent.id), "messages": [{"role": "user", "content": "Hello"}]},
        headers=auth_headers,
    )

    assert resp.json()["system_prompt"] == chat_calls[0]["system_prompt"]


@pytest.mark.asyncio
async def test_sandbox_chat_never_dials_a_phone(
    client, db_session, tenant_id, auth_headers, chat_calls, placed_calls
):
    """The entire point of this endpoint — text only, no telephony."""
    prospect = await _researched_prospect(db_session, tenant_id)
    agent = await _agent(db_session, tenant_id)

    await client.post(
        f"/api/prospects/{prospect.id}/sandbox-chat",
        json={"agent_id": str(agent.id), "messages": [{"role": "user", "content": "Hello"}]},
        headers=auth_headers,
    )

    assert placed_calls == []


@pytest.mark.asyncio
async def test_sandbox_chat_does_not_advance_outreach_counters(
    client, db_session, tenant_id, auth_headers, chat_calls
):
    """Nobody at the company was reached — a text test must not move campaign state."""
    prospect = await _researched_prospect(db_session, tenant_id)
    agent = await _agent(db_session, tenant_id)

    await client.post(
        f"/api/prospects/{prospect.id}/sandbox-chat",
        json={"agent_id": str(agent.id), "messages": [{"role": "user", "content": "Hello"}]},
        headers=auth_headers,
    )

    refreshed = await prospect_service.get_prospect(db_session, prospect.id, tenant_id)
    assert refreshed.call_count == 0
    assert refreshed.outreach_status == "not_reached"


@pytest.mark.asyncio
async def test_sandbox_chat_disables_tools(client, db_session, tenant_id, auth_headers, chat_calls):
    """book_appointment/create_lead must never fire against this specific real
    prospect's calendar/CRM just because the operator was testing a pitch.
    """
    prospect = await _researched_prospect(db_session, tenant_id)
    agent = await _agent(db_session, tenant_id)

    await client.post(
        f"/api/prospects/{prospect.id}/sandbox-chat",
        json={"agent_id": str(agent.id), "messages": [{"role": "user", "content": "Hello"}]},
        headers=auth_headers,
    )

    assert chat_calls[0]["tools_enabled"] is False


@pytest.mark.asyncio
async def test_sandbox_chat_and_real_call_inject_identical_personalization(
    client, db_session, tenant_id, auth_headers, chat_calls, placed_calls
):
    """The guarantee the whole feature rests on: what you read in the sandbox chat is
    what the real call will say. Both paths call script_service.build_prospect_prompt
    with the same arguments, so this fails the moment one of them drifts.
    """
    prospect = await _researched_prospect(
        db_session, tenant_id, notes="Owner is Maria, only answers before 9am."
    )
    agent = await _agent(db_session, tenant_id)

    await client.post(
        f"/api/prospects/{prospect.id}/sandbox-chat",
        json={"agent_id": str(agent.id), "messages": [{"role": "user", "content": "Hello"}]},
        headers=auth_headers,
    )
    await client.post(
        f"/api/prospects/{prospect.id}/call",
        json={"agent_id": str(agent.id)},
        headers=auth_headers,
    )

    chat_prompt = chat_calls[0]["system_prompt"]
    call_prompt = placed_calls[0]["prompt"]
    assert chat_prompt == call_prompt
    assert "[ROLE] You are Alex." in chat_prompt
    assert "Family-run HVAC installer" in chat_prompt
    assert "Owner is Maria" in chat_prompt


@pytest.mark.asyncio
async def test_sandbox_chat_passes_through_the_chosen_model(
    client, db_session, tenant_id, auth_headers, chat_calls
):
    prospect = await _researched_prospect(db_session, tenant_id)
    agent = await _agent(db_session, tenant_id)

    await client.post(
        f"/api/prospects/{prospect.id}/sandbox-chat",
        json={
            "agent_id": str(agent.id),
            "messages": [{"role": "user", "content": "Hello"}],
            "model": "gpt-4o-mini",
        },
        headers=auth_headers,
    )

    assert chat_calls[0]["model"] == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_sandbox_chat_requires_ready_research(
    client, db_session, tenant_id, auth_headers, chat_calls
):
    prospect = await _make_prospect(db_session, tenant_id)  # research_status stays "pending"
    agent = await _agent(db_session, tenant_id)

    resp = await client.post(
        f"/api/prospects/{prospect.id}/sandbox-chat",
        json={"agent_id": str(agent.id), "messages": [{"role": "user", "content": "Hello"}]},
        headers=auth_headers,
    )

    assert resp.status_code == 422
    assert chat_calls == []


@pytest.mark.asyncio
async def test_sandbox_chat_404s_for_unknown_agent(
    client, db_session, tenant_id, auth_headers, chat_calls
):
    prospect = await _researched_prospect(db_session, tenant_id)

    resp = await client.post(
        f"/api/prospects/{prospect.id}/sandbox-chat",
        json={"agent_id": str(uuid.uuid4()), "messages": [{"role": "user", "content": "Hello"}]},
        headers=auth_headers,
    )

    assert resp.status_code == 404
    assert chat_calls == []


@pytest.mark.asyncio
async def test_sandbox_chat_is_tenant_scoped(
    client, db_session, tenant_id, other_auth_headers, chat_calls
):
    prospect = await _researched_prospect(db_session, tenant_id)
    agent = await _agent(db_session, tenant_id)

    resp = await client.post(
        f"/api/prospects/{prospect.id}/sandbox-chat",
        json={"agent_id": str(agent.id), "messages": [{"role": "user", "content": "Hello"}]},
        headers=other_auth_headers,
    )

    assert resp.status_code == 404
    assert chat_calls == []
