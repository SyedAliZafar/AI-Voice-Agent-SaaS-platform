"""WebSocket endpoint for live call monitoring.

Dashboard clients subscribe to a call_id and receive real-time events
(transcript deltas, tool calls, sentiment updates) via Redis PubSub.
"""

import json

import redis.asyncio as redis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.config import get_settings

router = APIRouter()
settings = get_settings()


@router.websocket("/ws/calls/{call_id}")
async def call_stream(websocket: WebSocket, call_id: str):
    await websocket.accept()
    redis_client = redis.from_url(settings.redis_url)
    pubsub = redis_client.pubsub()
    channel = f"call:{call_id}"
    await pubsub.subscribe(channel)

    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                await websocket.send_text(message["data"].decode())
    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe(channel)
        await redis_client.close()


async def publish_call_event(call_id: str, event: dict) -> None:
    """Called by the webhook handler to broadcast an event to subscribers."""
    redis_client = redis.from_url(settings.redis_url)
    await redis_client.publish(f"call:{call_id}", json.dumps(event))
    await redis_client.close()
