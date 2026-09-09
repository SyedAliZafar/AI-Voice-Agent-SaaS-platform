"""Tests for serial, event-chained batch outreach runs (backend/services/batch_service.py).

The property that matters most here isn't "does it dial" — /batch-call already covers
that loop. It's that a call's terminal webhook can fire more than once
(call_service._fanout_post_call's own documented contract) without ever dialing a
prospect twice, and that a call unrelated to any batch run is a safe no-op. Most tests
below are built around those two guarantees rather than around happy-path dialing alone.
"""

import uuid

import pytest

from backend.schemas.prospect import CompanyResearch
from backend.services import batch_service, call_service, prospect_service
from backend.workers import batch_tasks


async def _prospect(db_session, tenant_id, name="RoofCo", phone="+441170000001", **place_extra):
    place = {"google_place_id": f"p_{uuid.uuid4().hex}", "name": name, **place_extra}
    [prospect] = await prospect_service.upsert_from_places(db_session, tenant_id, [place], "q")
    prospect.phone = phone
    await db_session.commit()
    return prospect


async def _researched_prospect(db_session, tenant_id, name="RoofCo", phone="+441170000001"):
    prospect = await _prospect(db_session, tenant_id, name=name, phone=phone)
    await prospect_service.mark_research_ready(
        db_session, prospect.id, CompanyResearch(summary="Family-run roofer")
    )
    return await prospect_service.get_prospect(db_session, prospect.id, tenant_id)


async def _agent(db_session, tenant_id):
    from backend.schemas.agent import AgentCreate
    from backend.services import agent_service

    return await agent_service.create_agent(
        db_session,
        tenant_id,
        AgentCreate(name="SDR", system_prompt="[ROLE] You are Alex.", platform="retell"),
    )


@pytest.fixture
def placed_calls(monkeypatch) -> list[dict]:
    """Capture local-agent dials instead of spending a real, billed call, but still
    write the Call row the real place_test_call would — batch_service looks that row up
    by external_id right after dialing (to stamp BatchRunItem.call_id), and tests below
    simulate that call's terminal webhook, so a real row has to exist.

    Patched on the shared test_call_service module object, so batch_service's own
    import of it sees the same fake — same trick tests/test_prospects.py uses for the
    /call and /batch-call routes.
    """
    from backend.services import test_call_service

    calls: list[dict] = []

    async def fake_place_test_call(
        db, agent_id, tenant_id, to_number, system_prompt_override=None, prospect_id=None
    ):
        call_id = f"mock_call_{len(calls) + 1}"
        calls.append({"agent_id": agent_id, "to_number": to_number, "prospect_id": prospect_id})
        await call_service.create_outbound_call_record(
            db, tenant_id, agent_id, call_id, to_number, prospect_id=prospect_id
        )
        return {"call_id": call_id, "from_number": "+10000000000", "status": "dialing"}

    monkeypatch.setattr(test_call_service, "place_test_call", fake_place_test_call)
    return calls


@pytest.fixture
def failing_call(monkeypatch) -> None:
    """Every dial raises TestCallError — for exercising the skip-and-continue path."""
    from backend.services import test_call_service

    async def fake_place_test_call(*args, **kwargs):
        raise test_call_service.TestCallError("Retell rejected the call")

    monkeypatch.setattr(test_call_service, "place_test_call", fake_place_test_call)


@pytest.fixture
def placed_platform_calls(monkeypatch) -> list[dict]:
    """Capture platform-agent (ADR-012) dials, and stand in for the agent's declared
    {{placeholders}} so per-prospect variable resolution can be asserted without Retell.
    """
    from backend.services import test_call_service

    calls: list[dict] = []

    async def fake_declared(external_agent_id, platform="retell"):
        return ["company_name", "contact_name", "city"]

    async def fake_place(
        db, tenant_id, external_agent_id, to_number, dynamic_variables=None, prospect_id=None
    ):
        calls.append({"to_number": to_number, "dynamic_variables": dynamic_variables})
        call_id = f"mock_ext_call_{len(calls)}"
        await call_service.create_outbound_call_record(
            db, tenant_id, None, call_id, to_number,
            prospect_id=prospect_id, external_agent_id=external_agent_id,
        )
        return {"call_id": call_id, "from_number": "+10000000000", "status": "dialing"}

    monkeypatch.setattr(test_call_service, "get_platform_agent_variables", fake_declared)
    monkeypatch.setattr(test_call_service, "place_platform_agent_call", fake_place)
    return calls


@pytest.fixture
def batch_advance_calls(monkeypatch) -> list[str]:
    """Capture advance_batch_run.delay() instead of dispatching to the real Celery
    broker — same idea as conftest's autouse `queued_research` fixture for
    prospect_tasks.research_prospect, just not autouse since only batch tests need it.
    """
    queued: list[str] = []
    monkeypatch.setattr(
        batch_tasks.advance_batch_run, "delay", lambda run_id: queued.append(run_id)
    )
    return queued


@pytest.mark.asyncio
async def test_start_run_dials_only_the_first_item(db_session, tenant_id, placed_calls):
    a = await _researched_prospect(db_session, tenant_id, "A", "+441170000001")
    b = await _researched_prospect(db_session, tenant_id, "B", "+441170000002")
    agent = await _agent(db_session, tenant_id)

    run = await batch_service.start_run(
        db_session,
        tenant_id,
        agent_id=agent.id,
        external_agent_id=None,
        limit=10,
        city=None,
        max_call_count=0,
        dynamic_variables={},
    )

    assert run.total == 2
    assert len(placed_calls) == 1  # not both — that's the whole point
    by_prospect = {item.prospect_id: item.status for item in run.items}
    assert by_prospect[a.id] == "dialing"
    assert by_prospect[b.id] == "queued"


@pytest.mark.asyncio
async def test_start_run_raises_when_nothing_is_eligible(db_session, tenant_id):
    with pytest.raises(batch_service.BatchRunError):
        await batch_service.start_run(
            db_session,
            tenant_id,
            agent_id=uuid.uuid4(),
            external_agent_id=None,
            limit=10,
            city=None,
            max_call_count=0,
            dynamic_variables={},
        )


@pytest.mark.asyncio
async def test_start_run_raises_for_unknown_agent(db_session, tenant_id):
    await _researched_prospect(db_session, tenant_id)

    with pytest.raises(batch_service.BatchRunError, match="Agent not found"):
        await batch_service.start_run(
            db_session,
            tenant_id,
            agent_id=uuid.uuid4(),
            external_agent_id=None,
            limit=10,
            city=None,
            max_call_count=0,
            dynamic_variables={},
        )


@pytest.mark.asyncio
async def test_a_call_ending_dials_the_next_item(
    db_session, tenant_id, placed_calls, batch_advance_calls
):
    """The real mechanism: no timer, no cursor increment — the next dial only happens
    because the previous call's terminal webhook fires _fanout_post_call.
    """
    await _researched_prospect(db_session, tenant_id, "A", "+441170000001")
    await _researched_prospect(db_session, tenant_id, "B", "+441170000002")
    agent = await _agent(db_session, tenant_id)

    run = await batch_service.start_run(
        db_session,
        tenant_id,
        agent_id=agent.id,
        external_agent_id=None,
        limit=10,
        city=None,
        max_call_count=0,
        dynamic_variables={},
    )
    assert len(placed_calls) == 1

    call = await call_service.get_call_by_external_id(db_session, "mock_call_1")
    assert call is not None

    await call_service.handle_call_ended(
        db_session,
        call.external_id,
        {"call_status": "ended", "disconnection_reason": "dial_no_answer"},
    )

    # _fanout_post_call only enqueues the next dial — it never dials inline (ADR-005).
    assert batch_advance_calls == [str(run.id)]

    # Running the enqueued task is what actually places call #2.
    await batch_service.advance_run(db_session, run.id)
    assert len(placed_calls) == 2

    refreshed = await batch_service.get_run(db_session, tenant_id, run.id)
    statuses = {item.status for item in refreshed.items}
    assert statuses == {"done", "dialing"}


@pytest.mark.asyncio
async def test_call_ending_twice_advances_the_run_only_once(
    db_session, tenant_id, placed_calls, batch_advance_calls
):
    """call_ended and call_analyzed both reach a terminal Call.status and both fan out
    (call_service._fanout_post_call's documented contract) — a second terminal report
    for the same call must not dial a third prospect.
    """
    await _researched_prospect(db_session, tenant_id, "A", "+441170000001")
    await _researched_prospect(db_session, tenant_id, "B", "+441170000002")
    agent = await _agent(db_session, tenant_id)

    run = await batch_service.start_run(
        db_session,
        tenant_id,
        agent_id=agent.id,
        external_agent_id=None,
        limit=10,
        city=None,
        max_call_count=0,
        dynamic_variables={},
    )
    call = await call_service.get_call_by_external_id(db_session, "mock_call_1")

    await call_service.handle_call_ended(db_session, call.external_id, {"call_status": "ended"})
    await call_service.handle_call_analyzed(
        db_session, call.external_id, {"call_analysis": {"user_sentiment": "Neutral"}}
    )

    # Only the first terminal report should have enqueued an advance.
    assert batch_advance_calls == [str(run.id)]


@pytest.mark.asyncio
async def test_mark_item_done_and_advance_ignores_calls_outside_any_batch(db_session, tenant_id):
    """A prospect called via the plain /call button (or the old /batch-call loop) has
    prospect_id set but no batch item — must be a no-op, not an error.
    """
    prospect = await _researched_prospect(db_session, tenant_id)
    call = await call_service.create_outbound_call_record(
        db_session, tenant_id, uuid.uuid4(), "solo_call", "+441170000001", prospect_id=prospect.id
    )

    run_id = await batch_service.mark_item_done_and_advance(db_session, call)

    assert run_id is None
    # And the session must still be usable afterwards — regression guard for the earlier
    # bug where an unconditional rollback() here corrupted the ambient transaction.
    refreshed = await prospect_service.get_prospect(db_session, prospect.id, tenant_id)
    assert refreshed is not None


@pytest.mark.asyncio
async def test_advance_run_skips_a_failing_dial_and_moves_on(db_session, tenant_id, failing_call):
    await _researched_prospect(db_session, tenant_id, "A", "+441170000001")
    await _researched_prospect(db_session, tenant_id, "B", "+441170000002")
    agent = await _agent(db_session, tenant_id)

    run = await batch_service.start_run(
        db_session,
        tenant_id,
        agent_id=agent.id,
        external_agent_id=None,
        limit=10,
        city=None,
        max_call_count=0,
        dynamic_variables={},
    )

    # Every item failed to dial (fixture raises on every call), so the run should have
    # tried both, skipped both, and finished itself rather than stalling forever.
    refreshed = await batch_service.get_run(db_session, tenant_id, run.id)
    assert refreshed.status == "done"
    assert all(item.status == "skipped" for item in refreshed.items)


@pytest.mark.asyncio
async def test_each_call_gets_its_own_prospects_company_name(
    db_session, tenant_id, placed_platform_calls, batch_advance_calls
):
    """The bug this exists to prevent: one {{company_name}} typed into the batch form
    and every company in the run gets introduced by the same name. Per-prospect
    placeholders are resolved per dial, server-side, and beat the run-level value.
    """
    a = await _prospect(db_session, tenant_id, "Alpha Roofing", "+441170000001")
    a.city = "Derby"
    b = await _prospect(db_session, tenant_id, "Beta Roofing", "+441170000002")
    b.city = "Leeds"
    await db_session.commit()

    run = await batch_service.start_run(
        db_session,
        tenant_id,
        agent_id=None,
        external_agent_id="agent_ext_1",
        prospect_ids=[a.id, b.id],
        limit=10,
        city=None,
        max_call_count=0,
        dynamic_variables={"company_name": "TYPED ONCE", "contact_name": "Maria"},
    )

    # First dial carries Alpha's own name and city, not the typed-once value.
    assert placed_platform_calls[0]["dynamic_variables"]["company_name"] == "Alpha Roofing"
    assert placed_platform_calls[0]["dynamic_variables"]["city"] == "Derby"
    # A genuinely batch-wide value the operator typed still comes through untouched.
    assert placed_platform_calls[0]["dynamic_variables"]["contact_name"] == "Maria"

    # Advancing to the second prospect re-resolves them against *that* prospect.
    call = await call_service.get_call_by_external_id(db_session, "mock_ext_call_1")
    await call_service.handle_call_ended(db_session, call.external_id, {"call_status": "ended"})
    await batch_service.advance_run(db_session, run.id)

    assert placed_platform_calls[1]["dynamic_variables"]["company_name"] == "Beta Roofing"
    assert placed_platform_calls[1]["dynamic_variables"]["city"] == "Leeds"


@pytest.mark.asyncio
async def test_a_prospect_missing_a_required_variable_is_skipped_not_fatal(
    db_session, tenant_id, placed_platform_calls, batch_advance_calls
):
    """The batch panel tells the operator a prospect with nothing on file for a required
    placeholder "gets skipped" — this is that promise. It must skip *that prospect* and
    carry on, not abort the run: the alternative is one thin record stopping the other
    fourteen calls.
    """
    from backend.services import test_call_service

    # The stub agent declares city; give the first prospect none.
    no_city = await _prospect(db_session, tenant_id, "No City Roofing", "+441170000001")
    fine = await _prospect(db_session, tenant_id, "Complete Roofing", "+441170000002")
    fine.city = "Derby"
    await db_session.commit()

    # Restore the real validation, which is what actually rejects the blank.
    real_place = test_call_service.place_platform_agent_call

    async def validating_place(
        db, tenant_id_, external_agent_id, to_number, dynamic_variables=None, prospect_id=None
    ):
        declared = await test_call_service.get_platform_agent_variables(external_agent_id)
        test_call_service._resolve_call_variables(declared, "stub agent", dynamic_variables)
        return await real_place(
            db, tenant_id_, external_agent_id, to_number,
            dynamic_variables=dynamic_variables, prospect_id=prospect_id,
        )

    test_call_service.place_platform_agent_call = validating_place
    try:
        run = await batch_service.start_run(
            db_session,
            tenant_id,
            agent_id=None,
            external_agent_id="agent_ext_1",
            prospect_ids=[no_city.id, fine.id],
            limit=10,
            city=None,
            max_call_count=0,
            dynamic_variables={},
        )
    finally:
        test_call_service.place_platform_agent_call = real_place

    items = {i.prospect_id: i for i in run.items}
    assert items[no_city.id].status == "skipped"
    assert "city" in (items[no_city.id].skip_reason or "")
    # The run moved straight on and dialed the next one instead of stopping.
    assert items[fine.id].status == "dialing"
    assert placed_platform_calls[0]["to_number"] == fine.phone


@pytest.mark.asyncio
async def test_explicit_prospect_ids_are_called_in_the_given_order(
    db_session, tenant_id, placed_platform_calls, batch_advance_calls
):
    """Ticked rows are the batch. Order is the operator's, and eligibility filters that
    exist to *choose* targets don't get to drop one they picked — here, a prospect
    already called twice, which batch_call_targets would never surface on its own.
    """
    first = await _prospect(db_session, tenant_id, "Second Choice", "+441170000002")
    already_called = await _prospect(db_session, tenant_id, "Already Called", "+441170000003")
    await prospect_service.record_call(db_session, already_called.id, tenant_id)
    await prospect_service.record_call(db_session, already_called.id, tenant_id)

    run = await batch_service.start_run(
        db_session,
        tenant_id,
        agent_id=None,
        external_agent_id="agent_ext_1",
        prospect_ids=[already_called.id, first.id],
        limit=10,
        city=None,
        max_call_count=0,
        dynamic_variables={},
    )

    ordered = [item.prospect_id for item in sorted(run.items, key=lambda i: i.position)]
    assert ordered == [already_called.id, first.id]
    assert placed_platform_calls[0]["to_number"] == already_called.phone


@pytest.mark.asyncio
async def test_explicit_ids_from_another_tenant_are_refused(
    db_session, tenant_id, other_tenant_id, placed_platform_calls
):
    theirs = await _prospect(db_session, other_tenant_id, "Not Yours", "+441170000009")

    with pytest.raises(batch_service.BatchRunError):
        await batch_service.start_run(
            db_session,
            tenant_id,
            agent_id=None,
            external_agent_id="agent_ext_1",
            prospect_ids=[theirs.id],
            limit=10,
            city=None,
            max_call_count=0,
            dynamic_variables={},
        )
    assert placed_platform_calls == []


@pytest.mark.asyncio
async def test_cancel_run_stops_future_dials(
    db_session, tenant_id, placed_calls, batch_advance_calls
):
    await _researched_prospect(db_session, tenant_id, "A", "+441170000001")
    await _researched_prospect(db_session, tenant_id, "B", "+441170000002")
    agent = await _agent(db_session, tenant_id)

    run = await batch_service.start_run(
        db_session,
        tenant_id,
        agent_id=agent.id,
        external_agent_id=None,
        limit=10,
        city=None,
        max_call_count=0,
        dynamic_variables={},
    )

    cancelled = await batch_service.cancel_run(db_session, tenant_id, run.id)
    assert cancelled.status == "cancelled"

    call = await call_service.get_call_by_external_id(db_session, "mock_call_1")
    await call_service.handle_call_ended(db_session, call.external_id, {"call_status": "ended"})
    await batch_service.advance_run(db_session, run.id)  # what the enqueued task would run

    assert len(placed_calls) == 1  # the second item was never dialed
    refreshed = await batch_service.get_run(db_session, tenant_id, run.id)
    still_queued = [item for item in refreshed.items if item.status == "queued"]
    assert len(still_queued) == 1
