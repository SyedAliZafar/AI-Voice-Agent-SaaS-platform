"""Tests for the NdaDispatch record and its uniqueness guarantee (phase5 Session 3).

There is no router yet (Session 6) and no send worker (Session 5), so this file covers the
one property the table exists for: **the database, not application code, is what stops a
second NDA going out for the same lead call.**

That property is the whole reason this is a table rather than two columns on Lead. ADR-009's
duplicate-tool ledger lives in a Python set on a websocket connection and dies with it — it
cannot see a retried Celery task, a second call_analyzed webhook, or a reconcile. So the
test that matters here is an integrity error, not a service call.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from backend.models.call import Call
from backend.models.lead import Lead
from backend.models.nda import NDA_STATES, NDA_TERMINAL_STATES, NdaDispatch
from backend.models.tenant import Tenant


async def _lead_and_call(db, tenant_id: uuid.UUID) -> tuple[Lead, Call]:
    lead = Lead(tenant_id=tenant_id, phone="+491701111111", business_name="Acme HVAC")
    db.add(lead)
    await db.flush()
    call = Call(
        tenant_id=tenant_id,
        agent_id=uuid.uuid4(),
        caller_number="+491701111111",
        status="resolved",
        started_at=datetime.now(UTC),
        external_id=f"ext-{uuid.uuid4()}",
        lead_id=lead.id,
    )
    db.add(call)
    await db.flush()
    return lead, call


def _dispatch(tenant_id: uuid.UUID, lead: Lead, call: Call, **overrides) -> NdaDispatch:
    kwargs = {
        "tenant_id": tenant_id,
        "lead_id": lead.id,
        "call_id": call.id,
        "recipient_email": "owner@acmehvac.example",
        "recipient_name": "Dana Okafor",
    }
    kwargs.update(overrides)
    return NdaDispatch(**kwargs)


@pytest.mark.asyncio
async def test_dispatch_defaults_to_pending_review(db_session, tenant_id):
    """The entry state is human review, not "queued". A legal document doesn't go out on
    an extraction's word alone — see models/nda.py on the rejected mid-call gate."""
    lead, call = await _lead_and_call(db_session, tenant_id)
    dispatch = _dispatch(tenant_id, lead, call)
    db_session.add(dispatch)
    await db_session.commit()

    assert dispatch.state == "pending_review"
    assert dispatch.attempt_count == 0
    assert dispatch.sent_at is None
    assert dispatch.signed_document_url is None


@pytest.mark.asyncio
async def test_second_dispatch_for_the_same_lead_call_is_rejected(db_session, tenant_id):
    """THE test in this file. An at-least-once Celery delivery must not become an
    at-least-once legal document."""
    lead, call = await _lead_and_call(db_session, tenant_id)
    db_session.add(_dispatch(tenant_id, lead, call))
    await db_session.commit()

    db_session.add(_dispatch(tenant_id, lead, call, recipient_email="someone.else@example.com"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_a_later_call_to_the_same_lead_can_get_its_own_nda(db_session, tenant_id):
    """Why call_id is in the uniqueness key and not just provenance: the same lead phoned
    again for a different engagement is a legitimate second NDA, and keying on lead_id
    alone would silently block it forever."""
    lead, first_call = await _lead_and_call(db_session, tenant_id)
    db_session.add(_dispatch(tenant_id, lead, first_call))
    await db_session.commit()

    second_call = Call(
        tenant_id=tenant_id,
        agent_id=uuid.uuid4(),
        caller_number="+491701111111",
        status="resolved",
        started_at=datetime.now(UTC),
        external_id=f"ext-{uuid.uuid4()}",
        lead_id=lead.id,
    )
    db_session.add(second_call)
    await db_session.flush()

    db_session.add(_dispatch(tenant_id, lead, second_call))
    await db_session.commit()  # must not raise


@pytest.mark.asyncio
async def test_blocked_state_records_agreement_without_an_email(db_session, tenant_id):
    """"They said yes but we couldn't get an address" has to be visible and fixable, not
    dropped — Lead.email is nullable and Bark doesn't always supply one."""
    lead, call = await _lead_and_call(db_session, tenant_id)
    dispatch = _dispatch(
        tenant_id, lead, call, recipient_email=None, state="blocked", extraction_confidence=0.91
    )
    db_session.add(dispatch)
    await db_session.commit()

    assert dispatch.state == "blocked"
    assert dispatch.recipient_email is None
    assert dispatch.extraction_confidence == pytest.approx(0.91)


@pytest.mark.asyncio
async def test_extraction_evidence_is_persisted_for_the_reviewer(db_session, tenant_id):
    """The quote is what makes an approve/reject decision take five seconds instead of a
    transcript read, and it's the only way to audit a bad extraction afterwards."""
    lead, call = await _lead_and_call(db_session, tenant_id)
    quote = "Yeah, go ahead and email the NDA to owner at acmehvac dot example."
    db_session.add(
        _dispatch(tenant_id, lead, call, extraction_quote=quote, extraction_confidence=0.84)
    )
    await db_session.commit()

    from sqlalchemy import select

    stored = (
        await db_session.execute(select(NdaDispatch).where(NdaDispatch.lead_id == lead.id))
    ).scalar_one()
    assert stored.extraction_quote == quote


def test_state_vocabulary_is_self_consistent():
    """Guards against a terminal state being added to one tuple and not the other."""
    assert set(NDA_TERMINAL_STATES) <= set(NDA_STATES)
    assert "pending_review" in NDA_STATES
    # "sending" must exist and must NOT be terminal: it's the ambiguous
    # IntegrationTimeoutError state, settled by asking the provider rather than retrying.
    assert "sending" in NDA_STATES
    assert "sending" not in NDA_TERMINAL_STATES


@pytest.mark.asyncio
async def test_tenant_nda_auto_send_defaults_off(db_session):
    """The default has to be off: the top failure mode of this feature is an email address
    heard over a phone line, and the cost of being wrong is a legal document sent to a
    stranger."""
    tenant = Tenant(name="Acme")
    db_session.add(tenant)
    await db_session.commit()

    assert tenant.nda_auto_send is False
    assert tenant.nda_company_legal_name is None


@pytest.mark.asyncio
async def test_tenant_legal_name_is_separate_from_display_name(db_session):
    """An NDA naming the wrong entity isn't enforceable, and `name` is edited freely by
    the UI — so the legal entity gets its own column."""
    tenant = Tenant(name="Acme", nda_company_legal_name="Acme Digital Ltd.")
    db_session.add(tenant)
    await db_session.commit()

    assert tenant.name == "Acme"
    assert tenant.nda_company_legal_name == "Acme Digital Ltd."
