"""Voice platform webhook receivers.

CRITICAL: these must respond in <200ms. Do the minimum synchronously
(create/update the Call row, publish to Redis), then enqueue everything
else (transcript processing, sentiment, CRM sync) as Celery tasks.
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.schemas.webhook import RetellWebhookEvent, VapiWebhookEvent
from backend.services import call_service
from backend.workers.transcript_tasks import process_transcript

router = APIRouter()


@router.post("/retell")
async def retell_webhook(
    payload: RetellWebhookEvent, request: Request, db: AsyncSession = Depends(get_db)
):
    if payload.event == "call_started":
        await call_service.handle_call_started(payload.call_id, platform="retell")
    elif payload.event == "transcript_update":
        await call_service.handle_transcript_update(db, payload.call_id, payload.transcript or "")
    elif payload.event == "call_ended":
        await call_service.handle_call_ended(db, payload.call_id)
        process_transcript.delay(payload.call_id)

    return {"status": "received"}


@router.post("/vapi")
async def vapi_webhook(
    payload: VapiWebhookEvent, request: Request, db: AsyncSession = Depends(get_db)
):
    call_id = payload.call.get("id", "")

    if payload.type == "call-start":
        await call_service.handle_call_started(call_id, platform="vapi")
    elif payload.type == "call-end":
        await call_service.handle_call_ended(db, call_id)
        process_transcript.delay(call_id)

    return {"status": "received"}
