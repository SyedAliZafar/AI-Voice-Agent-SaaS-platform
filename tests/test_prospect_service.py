"""Tests for prospect ranking, dedupe-upsert, and research status transitions."""

import pytest

from backend.schemas.prospect import CompanyResearch
from backend.services import prospect_service


def test_compute_priority_rewards_rating_reviews_website_phone():
    bare = prospect_service.compute_priority(None, 0, None, None)
    full = prospect_service.compute_priority(5.0, 500, "https://x.com", "+491701234567")

    assert bare == 0.0
    assert full > bare


def test_compute_priority_orders_candidates_sensibly():
    strong = prospect_service.compute_priority(4.8, 300, "https://strong.com", "+49170")
    weak = prospect_service.compute_priority(3.0, 2, None, None)

    assert strong > weak


@pytest.mark.asyncio
async def test_upsert_from_places_dedupes_by_place_id(db_session, tenant_id):
    place = {
        "google_place_id": "place_1",
        "name": "Acme Dental",
        "website": "https://acmedental.com",
        "phone": "+491701234567",
        "address": "Berlin",
        "category": "Dentist",
        "rating": 4.5,
        "review_count": 120,
    }

    first = await prospect_service.upsert_from_places(db_session, tenant_id, [place], "dentists")
    assert len(first) == 1
    original_id = first[0].id

    updated_place = {**place, "rating": 4.9, "review_count": 200}
    second = await prospect_service.upsert_from_places(
        db_session, tenant_id, [updated_place], "dentists"
    )

    assert len(second) == 1
    assert second[0].id == original_id  # same row, not a duplicate
    assert second[0].rating == 4.9

    all_prospects = await prospect_service.list_prospects(db_session, tenant_id)
    assert len(all_prospects) == 1


@pytest.mark.asyncio
async def test_upsert_does_not_clobber_research_or_outreach_state(db_session, tenant_id):
    place = {"google_place_id": "place_2", "name": "Beta Clinic", "rating": 4.0, "review_count": 10}
    [prospect] = await prospect_service.upsert_from_places(
        db_session, tenant_id, [place], "clinics"
    )

    research = CompanyResearch(summary="Great clinic", industry="Healthcare")
    await prospect_service.mark_research_ready(db_session, prospect.id, research)
    await prospect_service.set_outreach_status(db_session, prospect.id, tenant_id, "reached")

    # Re-discovering the same place should not reset research/outreach.
    [again] = await prospect_service.upsert_from_places(db_session, tenant_id, [place], "clinics")

    assert again.research_status == "ready"
    assert again.outreach_status == "reached"
    assert again.research["summary"] == "Great clinic"


@pytest.mark.asyncio
async def test_list_prospects_orders_by_priority_desc(db_session, tenant_id):
    low = {"google_place_id": "p_low", "name": "Low", "rating": 2.0, "review_count": 1}
    high = {"google_place_id": "p_high", "name": "High", "rating": 5.0, "review_count": 500}
    await prospect_service.upsert_from_places(db_session, tenant_id, [low, high], "q")

    ordered = await prospect_service.list_prospects(db_session, tenant_id)

    assert [p.name for p in ordered] == ["High", "Low"]


@pytest.mark.asyncio
async def test_research_status_transitions(db_session, tenant_id):
    place = {"google_place_id": "p_status", "name": "StatusCo"}
    [prospect] = await prospect_service.upsert_from_places(db_session, tenant_id, [place], "q")
    assert prospect.research_status == "pending"

    await prospect_service.mark_research_running(db_session, prospect.id)
    running = await prospect_service.get_prospect(db_session, prospect.id, tenant_id)
    assert running.research_status == "running"

    await prospect_service.mark_research_failed(db_session, prospect.id, "scrape timeout")
    failed = await prospect_service.get_prospect(db_session, prospect.id, tenant_id)
    assert failed.research_status == "failed"
    assert failed.research_error == "scrape timeout"

    await prospect_service.mark_research_ready(
        db_session, prospect.id, CompanyResearch(summary="Recovered")
    )
    ready = await prospect_service.get_prospect(db_session, prospect.id, tenant_id)
    assert ready.research_status == "ready"
    assert ready.research_error is None  # cleared on success
    assert ready.research["summary"] == "Recovered"


@pytest.mark.asyncio
async def test_record_call_increments_count_and_flips_not_reached(db_session, tenant_id):
    place = {"google_place_id": "p_call", "name": "CallCo"}
    [prospect] = await prospect_service.upsert_from_places(db_session, tenant_id, [place], "q")
    assert prospect.outreach_status == "not_reached"

    await prospect_service.record_call(db_session, prospect.id, tenant_id)

    updated = await prospect_service.get_prospect(db_session, prospect.id, tenant_id)
    assert updated.call_count == 1
    assert updated.outreach_status == "reached"
    assert updated.last_called_at is not None
