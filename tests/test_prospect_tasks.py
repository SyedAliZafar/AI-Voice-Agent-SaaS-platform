"""Tests for the discovery task (Agent 1).

`_discover` had no coverage before this file: the `location` argument was being passed
to Google and then silently dropped on the floor instead of stored, and nothing failed.
These tests pin the whole argument path, from task input through to the stored row.

research_prospect's own path is covered in tests/test_prospects.py
(test_imported_prospect_reaches_research_ready_via_the_pipeline).
"""

import pytest

from backend.schemas.prospect import CompanyResearch
from backend.services import places_service, prospect_service
from backend.workers import prospect_tasks


def _session_factory(session):
    """Stand-in for prospect_tasks.AsyncSessionLocal — the task opens its own sessions
    (no HTTP request to borrow one from), so exercising the real body means substituting
    the factory. __aexit__ deliberately does not close; the fixture owns the lifetime.
    """

    class _Factory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return session

        async def __aexit__(self, *exc_info):
            return False

    return _Factory()


@pytest.fixture
def stub_places(monkeypatch):
    """Replace the billed Google call, capturing the arguments it was handed."""
    seen: dict = {}

    async def fake_search_places(query, location=None, radius_m=20_000, limit=20):
        seen.update(query=query, location=location, radius_m=radius_m, limit=limit)
        return [
            {
                "google_place_id": "place_solar_1",
                "name": "Bristol Solar Co",
                "address": "13 Harbury Rd, Bristol BS9 4PN, UK",
                "city": "Bristol",
                "country": "United Kingdom",
                "phone": "+441172510125",
            }
        ]

    monkeypatch.setattr(places_service, "search_places", fake_search_places)
    return seen


@pytest.mark.asyncio
async def test_discovery_stores_the_search_location(
    db_session, tenant_id, stub_places, monkeypatch, queued_research
):
    """The bug this column exists to fix: `location` reached Google but never the DB,
    so afterwards nothing recorded that these rows came from a Bristol-scoped search.
    """
    monkeypatch.setattr(prospect_tasks, "AsyncSessionLocal", _session_factory(db_session))

    await prospect_tasks._discover(str(tenant_id), "solar", "Bristol, UK", 20_000, 20)

    [prospect] = await prospect_service.list_prospects(db_session, tenant_id)
    assert prospect.source_query == "solar"
    assert prospect.source_location == "Bristol, UK"


@pytest.mark.asyncio
async def test_discovery_passes_its_arguments_through_to_places(
    db_session, tenant_id, stub_places, monkeypatch, queued_research
):
    monkeypatch.setattr(prospect_tasks, "AsyncSessionLocal", _session_factory(db_session))

    await prospect_tasks._discover(str(tenant_id), "solar", "Bristol, UK", 5_000, 7)

    assert stub_places == {
        "query": "solar",
        "location": "Bristol, UK",
        "radius_m": 5_000,
        "limit": 7,
    }


@pytest.mark.asyncio
async def test_discovery_stores_city_and_country(
    db_session, tenant_id, stub_places, monkeypatch, queued_research
):
    """End-to-end over the real task body: the structured fields places_service
    extracts must survive all the way into the row.
    """
    monkeypatch.setattr(prospect_tasks, "AsyncSessionLocal", _session_factory(db_session))

    await prospect_tasks._discover(str(tenant_id), "solar", "Bristol, UK", 20_000, 20)

    [prospect] = await prospect_service.list_prospects(db_session, tenant_id)
    assert prospect.city == "Bristol"
    assert prospect.country == "United Kingdom"


@pytest.mark.asyncio
async def test_discovery_with_no_location_stores_null(
    db_session, tenant_id, stub_places, monkeypatch, queued_research
):
    """location is optional on DiscoverRequest — an unscoped search must store None
    rather than an empty string, so "no location" has one representation.
    """
    monkeypatch.setattr(prospect_tasks, "AsyncSessionLocal", _session_factory(db_session))

    await prospect_tasks._discover(str(tenant_id), "solar", None, 20_000, 20)

    [prospect] = await prospect_service.list_prospects(db_session, tenant_id)
    assert prospect.source_location is None


@pytest.mark.asyncio
async def test_rediscovery_does_not_rewrite_the_original_search_location(
    db_session, tenant_id, stub_places, monkeypatch, queued_research
):
    """source_location records which search first found this row. A later, differently
    scoped search returning the same place must not retroactively rewrite that.
    """
    monkeypatch.setattr(prospect_tasks, "AsyncSessionLocal", _session_factory(db_session))

    await prospect_tasks._discover(str(tenant_id), "solar", "Bristol, UK", 20_000, 20)
    await prospect_tasks._discover(str(tenant_id), "solar", "Cardiff, UK", 20_000, 20)

    [prospect] = await prospect_service.list_prospects(db_session, tenant_id)
    assert prospect.source_location == "Bristol, UK"


@pytest.mark.asyncio
async def test_discovery_enqueues_research_only_for_new_rows(
    db_session, tenant_id, stub_places, monkeypatch, queued_research
):
    """Re-running a query shouldn't re-research prospects we already know."""
    monkeypatch.setattr(prospect_tasks, "AsyncSessionLocal", _session_factory(db_session))

    await prospect_tasks._discover(str(tenant_id), "solar", "Bristol, UK", 20_000, 20)
    assert len(queued_research) == 1

    [prospect] = await prospect_service.list_prospects(db_session, tenant_id)
    await prospect_service.mark_research_ready(db_session, prospect.id, CompanyResearch())

    await prospect_tasks._discover(str(tenant_id), "solar", "Bristol, UK", 20_000, 20)
    assert len(queued_research) == 1  # unchanged — the row is no longer "pending"
