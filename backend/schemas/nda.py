"""Pydantic schemas for NDA dispatch (phase5 Session 3).

The router that consumes these arrives in Session 6; they're defined now so the model and
its wire shape land together and the frontend's types.ts has something to mirror.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel


class NdaDispatchResponse(BaseModel):
    id: uuid.UUID
    lead_id: uuid.UUID
    call_id: uuid.UUID
    recipient_email: str | None
    recipient_name: str | None
    state: str

    extraction_confidence: float | None
    extraction_quote: str | None

    provider: str | None
    attempt_count: int
    last_error: str | None
    signed_document_url: str | None

    requested_at: datetime | None
    sent_at: datetime | None
    signed_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}

    # provider_request_id is deliberately absent: it's the provider's internal handle,
    # useful only to the webhook and the reconcile sweep, and there's no reason to
    # publish it to a browser.


class NdaApproveRequest(BaseModel):
    """Operator confirming a pending_review dispatch.

    `recipient_email` is editable and overrides whatever extraction proposed — that is the
    entire point of the review step. An address transcribed from speech is the most
    likely thing to be wrong in this flow, and the operator has the transcript in front of
    them.
    """

    recipient_email: str | None = None
    recipient_name: str | None = None
