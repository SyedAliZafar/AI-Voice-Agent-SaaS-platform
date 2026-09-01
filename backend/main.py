"""FastAPI application factory.

Entry point for the voice agent SaaS backend. Wires up routers, middleware,
and startup/shutdown hooks.
"""

import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api import (
    agents,
    analytics,
    calls,
    integrations,
    leads,
    phone_numbers,
    prospects,
    retell_ws,
    webhooks,
    ws,
)
from backend.config import get_settings
from backend.middleware.logging import setup_logging
from backend.services import llm_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()

    # Pay the LLM providers' DNS + TLS handshake here rather than on the first
    # caller's greeting (see llm_service.warm_up_providers for the measurements).
    # Deliberately a background task, never awaited: warming must not delay startup,
    # and on a machine with no outbound network it must not block it either. Retell
    # dials seconds-to-minutes after boot, so the warm-up always lands first in
    # practice — and if it somehow doesn't, the first call just costs what it costs
    # today. Cancel-and-suppress on shutdown mirrors retell_ws.py's task teardown.
    warmup_task = asyncio.create_task(llm_service.warm_up_providers())
    try:
        yield
    finally:
        warmup_task.cancel()
        with suppress(asyncio.CancelledError):
            await warmup_task


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Voice Agent SaaS API",
        version="0.1.0",
        lifespan=lifespan,
    )

    cors_kwargs: dict = {}
    if settings.environment == "development":
        # localhost and 127.0.0.1 are distinct CORS origins to the browser; accept
        # any loopback host/port in dev so the frontend works either way.
        cors_kwargs["allow_origin_regex"] = r"https?://(localhost|127\.0\.0\.1)(:\d+)?"

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_private_network=True,
        **cors_kwargs,
    )

    app.include_router(agents.router, prefix="/api/agents", tags=["agents"])
    app.include_router(calls.router, prefix="/api/calls", tags=["calls"])
    app.include_router(analytics.router, prefix="/api/analytics", tags=["analytics"])
    app.include_router(prospects.router, prefix="/api/prospects", tags=["prospects"])
    app.include_router(leads.router, prefix="/api/leads", tags=["leads"])
    app.include_router(integrations.router, prefix="/api/integrations", tags=["integrations"])
    app.include_router(phone_numbers.router, prefix="/api/phone-numbers", tags=["phone-numbers"])
    app.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
    app.include_router(ws.router, tags=["websocket"])
    app.include_router(retell_ws.router, tags=["websocket"])

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
