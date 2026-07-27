"""Redis-based rate limiting — protects webhook endpoints and public API
from abuse. Simple fixed-window counter; swap for a sliding window /
token bucket if you need smoother limits at scale.
"""

import redis.asyncio as redis
from fastapi import HTTPException, Request

from backend.config import get_settings

settings = get_settings()


async def rate_limit(request: Request, key_prefix: str, limit: int = 100, window_sec: int = 60):
    redis_client = redis.from_url(settings.redis_url)
    key = f"ratelimit:{key_prefix}:{request.client.host}"

    count = await redis_client.incr(key)
    if count == 1:
        await redis_client.expire(key, window_sec)

    await redis_client.close()

    if count > limit:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
