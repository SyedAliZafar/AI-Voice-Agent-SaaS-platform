"""Post-call async processing: transcript storage, sentiment, CRM sync."""

from backend.workers.async_bridge import run_sync as _run_sync
from backend.workers.celery_app import celery_app


@celery_app.task(name="process_transcript")
def process_transcript(call_id: str) -> None:
    """Runs after call_ended webhook. Fetches full transcript from the
    voice platform, stores it, computes sentiment, and syncs to CRM if
    configured. Sync entry point / async impl split — see async_bridge for why
    the coroutine runs on a shared per-process loop rather than asyncio.run().
    """
    _run_sync(_process(call_id))


async def _process(call_id: str) -> None:
    # 1. Fetch full transcript + recording URL from voice platform
    # 2. Store in Transcript table + upload audio to S3
    # 3. Run sentiment analysis (DeepSeek or a lightweight classifier)
    # 4. If agent has CRM integration configured, sync lead/contact
    pass
