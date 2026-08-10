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
    assert by_name["Acme HVAC"].address == "Berlin"  # city -> address
    assert by_name["Acme HVAC"].category == "hvac"  # niche -> category
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
    resp = await client.post(
        "/api/prospects/import-csv",
        files=_upload("company,telephone\nAcme,+491701234567\n"),
        headers=auth_headers,
    )

    assert resp.status_code == 422
    assert "business_name" in resp.json()["detail"]


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
