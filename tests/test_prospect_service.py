"""Tests for prospect ranking, dedupe-upsert, and research status transitions."""

import uuid

import pytest

from backend.schemas.prospect import CompanyResearch
from backend.services import call_service, prospect_service


async def _prospect(db_session, tenant_id, name="CallCo", **place_extra):
    place = {"google_place_id": f"p_{uuid.uuid4().hex}", "name": name, **place_extra}
    [prospect] = await prospect_service.upsert_from_places(db_session, tenant_id, [place], "q")
    return prospect


async def _terminal_call(db_session, tenant_id, prospect_id, **fields):
    call = await call_service.create_outbound_call_record(
        db_session,
        tenant_id,
        uuid.uuid4(),
        f"ext_{uuid.uuid4().hex}",
        "+441170000000",
        prospect_id=prospect_id,
    )
    call.status = fields.pop("status", "failed")
    for key, value in fields.items():
        setattr(call, key, value)
    await db_session.commit()
    return call


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


def test_normalize_category_keeps_only_the_verticals_we_sell_into():
    assert prospect_service.normalize_category("Roofing Contractor") == "Roofing"
    assert prospect_service.normalize_category("roofer") == "Roofing"
    assert prospect_service.normalize_category("Solar Energy Contractor") == "Solar"
    assert prospect_service.normalize_category("photovoltaic installer") == "Solar"
    # Everything else loses its label rather than minting a bucket in the operator's
    # category filter; None is what the UI shows as "Unspecified".
    assert prospect_service.normalize_category("Dental Clinic") is None
    assert prospect_service.normalize_category("British Restaurant") is None
    assert prospect_service.normalize_category("") is None
    assert prospect_service.normalize_category(None) is None


@pytest.mark.asyncio
async def test_upsert_normalizes_category(db_session, tenant_id):
    """Google's primaryTypeDisplayName is free text; the row must not carry it through."""
    [roofer] = await prospect_service.upsert_from_places(
        db_session,
        tenant_id,
        [
            {
                "google_place_id": "place_roof",
                "name": "Acme Roofing",
                "category": "Roofing Contractor",
            }
        ],
        "roofers",
    )
    assert roofer.category == "Roofing"

    [dentist] = await prospect_service.upsert_from_places(
        db_session,
        tenant_id,
        [{"google_place_id": "place_dds", "name": "Acme Dental", "category": "Dental Clinic"}],
        "dentists",
    )
    assert dentist.category is None


@pytest.mark.asyncio
async def test_upsert_persists_city_and_country(db_session, tenant_id):
    """places_service extracts these from Google's typed addressComponents; if the
    upsert drops them, every discovered prospect lands ungrouped.
    """
    place = {
        "google_place_id": "place_geo",
        "name": "Acme Solar",
        "address": "13 Harbury Rd, Bristol BS9 4PN, UK",
        "city": "Bristol",
        "country": "United Kingdom",
    }

    [created] = await prospect_service.upsert_from_places(db_session, tenant_id, [place], "solar")
    assert created.city == "Bristol"
    assert created.country == "United Kingdom"

    # A later run that resolves a different city (Google refined it) must update, and a
    # run that reports nothing must not wipe what we already knew.
    [moved] = await prospect_service.upsert_from_places(
        db_session, tenant_id, [{**place, "city": "Clevedon"}], "solar"
    )
    assert moved.city == "Clevedon"

    [unchanged] = await prospect_service.upsert_from_places(
        db_session, tenant_id, [{**place, "city": None, "country": None}], "solar"
    )
    assert unchanged.city == "Clevedon"
    assert unchanged.country == "United Kingdom"


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


@pytest.mark.asyncio
async def test_classify_no_answer_when_nobody_spoke(db_session, tenant_id):
    prospect = await _prospect(db_session, tenant_id)
    call = await _terminal_call(
        db_session,
        tenant_id,
        prospect.id,
        disconnection_reason="dial_no_answer",
        answered_by_human=False,
    )

    await prospect_service.classify_call_outcome(db_session, call)

    updated = await prospect_service.get_prospect(db_session, prospect.id, tenant_id)
    assert updated.status == "no_answer"


@pytest.mark.asyncio
async def test_classify_flags_a_human_rejection(db_session, tenant_id):
    prospect = await _prospect(db_session, tenant_id)
    call = await _terminal_call(
        db_session,
        tenant_id,
        prospect.id,
        status="resolved",
        disconnection_reason="user_hangup",
        answered_by_human=True,
        sentiment_score=0.0,
    )

    await prospect_service.classify_call_outcome(db_session, call)

    updated = await prospect_service.get_prospect(db_session, prospect.id, tenant_id)
    assert updated.status == "flagged"
    assert updated.outreach_status == "reached"


@pytest.mark.asyncio
async def test_classify_marks_called_for_a_neutral_conversation(db_session, tenant_id):
    prospect = await _prospect(db_session, tenant_id)
    call = await _terminal_call(
        db_session,
        tenant_id,
        prospect.id,
        status="resolved",
        answered_by_human=True,
        sentiment_score=0.5,
    )

    await prospect_service.classify_call_outcome(db_session, call)

    updated = await prospect_service.get_prospect(db_session, prospect.id, tenant_id)
    assert updated.status == "called"


@pytest.mark.asyncio
async def test_classify_marks_voicemail_even_when_the_machine_greeting_transcribed(
    db_session, tenant_id
):
    """The bug this rung was added for: answered_by_human is "did any turn come from the
    far end", and an answering machine's greeting IS such a turn — so every voicemail
    looked like a human who talked. Retell's voicemail_reached verdict must win.
    """
    prospect = await _prospect(db_session, tenant_id)
    call = await _terminal_call(
        db_session,
        tenant_id,
        prospect.id,
        status="failed",
        disconnection_reason="voicemail_reached",
        answered_by_human=True,  # the greeting was transcribed
        sentiment_score=0.5,
    )

    await prospect_service.classify_call_outcome(db_session, call)

    updated = await prospect_service.get_prospect(db_session, prospect.id, tenant_id)
    assert updated.status == "voicemail"
    # A machine picking up is not the prospect being reached.
    assert updated.outreach_status == "not_reached"


@pytest.mark.asyncio
async def test_resync_from_calls_can_move_status_back_down(db_session, tenant_id):
    """The whole-history path is allowed to correct what the per-call ladder ratcheted
    into place — without it, prospects misclassified before the voicemail fix would have
    stayed "called" forever.
    """
    prospect = await _prospect(db_session, tenant_id)
    await prospect_service.set_status(db_session, prospect.id, tenant_id, "called")

    voicemail = await _terminal_call(
        db_session,
        tenant_id,
        prospect.id,
        status="failed",
        disconnection_reason="voicemail_reached",
        answered_by_human=True,
    )

    await prospect_service.resync_status_from_calls(db_session, prospect, [voicemail])
    await db_session.commit()

    updated = await prospect_service.get_prospect(db_session, prospect.id, tenant_id)
    assert updated.status == "voicemail"


@pytest.mark.asyncio
async def test_resync_takes_the_best_outcome_not_the_latest(db_session, tenant_id):
    """A prospect who spoke to us once and hit voicemail since has still been reached."""
    prospect = await _prospect(db_session, tenant_id)
    spoke = await _terminal_call(
        db_session, tenant_id, prospect.id, status="resolved", answered_by_human=True
    )
    later_voicemail = await _terminal_call(
        db_session,
        tenant_id,
        prospect.id,
        status="failed",
        disconnection_reason="voicemail_reached",
        answered_by_human=True,
    )

    await prospect_service.resync_status_from_calls(db_session, prospect, [spoke, later_voicemail])
    await db_session.commit()

    updated = await prospect_service.get_prospect(db_session, prospect.id, tenant_id)
    assert updated.status == "called"


@pytest.mark.asyncio
async def test_resync_leaves_operator_set_status_alone(db_session, tenant_id):
    prospect = await _prospect(db_session, tenant_id)
    await prospect_service.set_status(db_session, prospect.id, tenant_id, "booked")
    call = await _terminal_call(
        db_session,
        tenant_id,
        prospect.id,
        status="failed",
        disconnection_reason="voicemail_reached",
    )

    await prospect_service.resync_status_from_calls(db_session, prospect, [call])
    await db_session.commit()

    updated = await prospect_service.get_prospect(db_session, prospect.id, tenant_id)
    assert updated.status == "booked"


@pytest.mark.asyncio
async def test_classify_never_downgrades_or_touches_operator_status(db_session, tenant_id):
    prospect = await _prospect(db_session, tenant_id)
    await prospect_service.set_status(db_session, prospect.id, tenant_id, "booked")

    call = await _terminal_call(
        db_session,
        tenant_id,
        prospect.id,
        disconnection_reason="dial_no_answer",
        answered_by_human=False,
    )
    await prospect_service.classify_call_outcome(db_session, call)

    updated = await prospect_service.get_prospect(db_session, prospect.id, tenant_id)
    assert updated.status == "booked"  # forward-only ladder never clobbers this


@pytest.mark.asyncio
async def test_classify_is_idempotent_and_forward_only(db_session, tenant_id):
    prospect = await _prospect(db_session, tenant_id)

    # call_ended arrives first with no sentiment yet — a human answered.
    ended = await _terminal_call(
        db_session,
        tenant_id,
        prospect.id,
        status="resolved",
        answered_by_human=True,
        sentiment_score=None,
    )
    await prospect_service.classify_call_outcome(db_session, ended)
    assert (
        await prospect_service.get_prospect(db_session, prospect.id, tenant_id)
    ).status == "called"

    # call_analyzed follows with negative sentiment — upgrade called -> flagged.
    ended.sentiment_score = 0.0
    await db_session.commit()
    await prospect_service.classify_call_outcome(db_session, ended)
    assert (
        await prospect_service.get_prospect(db_session, prospect.id, tenant_id)
    ).status == "flagged"

    # A late reconcile with the sentiment-less payload must not drag it back down.
    ended.sentiment_score = None
    await db_session.commit()
    await prospect_service.classify_call_outcome(db_session, ended)
    assert (
        await prospect_service.get_prospect(db_session, prospect.id, tenant_id)
    ).status == "flagged"


@pytest.mark.asyncio
async def test_batch_call_targets_filters_and_orders(db_session, tenant_id):
    await _prospect(db_session, tenant_id, name="NoPhone")
    weak = await _prospect(
        db_session, tenant_id, name="Weak", phone="+441170000001", rating=3.0, review_count=1
    )
    strong = await _prospect(
        db_session, tenant_id, name="Strong", phone="+441170000002", rating=5.0, review_count=400
    )
    await prospect_service.set_status(db_session, weak.id, tenant_id, "do_not_call")

    targets = await prospect_service.batch_call_targets(db_session, tenant_id, limit=10)

    assert [p.name for p in targets] == ["Strong"]  # no phone excluded, do_not_call excluded
    assert targets[0].id == strong.id


@pytest.mark.asyncio
async def test_batch_call_targets_respects_max_call_count(db_session, tenant_id):
    p = await _prospect(db_session, tenant_id, name="Called", phone="+441170000003")
    await prospect_service.record_call(db_session, p.id, tenant_id)

    assert await prospect_service.batch_call_targets(db_session, tenant_id, limit=10) == []
    reworked = await prospect_service.batch_call_targets(
        db_session, tenant_id, limit=10, max_call_count=1
    )
    assert [x.id for x in reworked] == [p.id]


@pytest.mark.asyncio
async def test_export_csv_has_phone_number_header_and_filters(db_session, tenant_id):
    a = await _prospect(db_session, tenant_id, name="Alpha", phone="+441170000004")
    await _prospect(db_session, tenant_id, name="Beta", phone="+441170000005")
    await prospect_service.set_status(db_session, a.id, tenant_id, "flagged")

    everything = await prospect_service.export_csv(db_session, tenant_id)
    assert everything.splitlines()[0].split(",")[0] == "phone number"
    assert "Alpha" in everything and "Beta" in everything

    flagged_only = await prospect_service.export_csv(db_session, tenant_id, status="flagged")
    assert "Alpha" in flagged_only and "Beta" not in flagged_only
