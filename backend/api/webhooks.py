"""Voice platform webhook receivers.

CRITICAL: these must respond in <200ms. Do the minimum synchronously
(create/update the Call row, publish to Redis), then enqueue everything
else (transcript processing, sentiment, CRM sync) as Celery tasks.

AUTH: deliberately NOT behind Depends(get_current_tenant) — Retell/Vapi call these
and cannot send our JWT. Instead the Retell route verifies the platform's own
X-Retell-Signature over the raw body (settings.retell_verify_webhooks, default on).
Calls are still resolved by the platform's external_id, and anything unmatched no-ops
rather than 500s (see call_service's module docstring).

Retell sends exactly three events — call_started, call_ended, call_analyzed — with the
call object NESTED under "call". See schemas/webhook.py for the history there.

Vapi still has no signature verification; it needs a separately configured shared secret
and isn't on the critical path today.
"""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.database import get_db
from backend.schemas.webhook import RetellWebhookEvent, VapiWebhookEvent
from backend.services import call_service
from backend.services.retell_adapter import RetellAdapter
from backend.workers.transcript_tasks import process_transcript

logger = logging.getLogger(__name__)
router = APIRouter()
settings = get_settings()


@router.post("/retell")
async def retell_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    # Read the RAW body first — signature verification is over the exact bytes received,
    # so this can't go through FastAPI's parsed-model injection.
    raw_body = (await request.body()).decode("utf-8")

    if settings.retell_verify_webhooks:
        adapter = RetellAdapter()
        if not adapter.verify_webhook_signature(
            raw_body, request.headers.get("X-Retell-Signature")
        ):
            logger.warning("retell webhook rejected: bad or missing signature")
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        payload = RetellWebhookEvent.model_validate(json.loads(raw_body))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail="Malformed Retell webhook payload") from exc

    call_id = payload.call_id
    if not call_id:
        logger.info("retell webhook with no call_id, ignoring", extra={"event": payload.event})
        return {"status": "received"}

    if payload.event == "call_started":
        await call_service.handle_call_started(call_id, platform="retell")
    elif payload.event == "call_ended":
        await call_service.handle_call_ended(db, call_id, payload.call)
        process_transcript.delay(call_id)
    elif payload.event == "call_analyzed":
        # Post-call analysis — this is where user_sentiment arrives.
        await call_service.handle_call_analyzed(db, call_id, payload.call)

    return {"status": "received"}


@router.post("/vapi")
async def vapi_webhook(
    payload: VapiWebhookEvent, request: Request, db: AsyncSession = Depends(get_db)
):
    call_id = payload.call.get("id", "")

    if payload.type == "call-start":
        await call_service.handle_call_started(call_id, platform="vapi")
    elif payload.type == "call-end":
        await call_service.handle_call_ended(db, call_id, payload.call)
        process_transcript.delay(call_id)

    return {"status": "received"}
