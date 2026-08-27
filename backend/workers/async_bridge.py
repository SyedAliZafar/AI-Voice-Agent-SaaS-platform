"""Bridge for running async service code from the sync Celery task bodies.

Every Celery task in this package is a thin sync wrapper around an async ``_impl``
coroutine. The naive ``asyncio.run(coro)`` spins up a fresh event loop per call and
closes it on return — which breaks SQLAlchemy's async engine: its asyncpg connection
pool binds each pooled connection to the loop that created it, so the *second* task in
a worker process gets handed a connection tied to the (now closed) first loop and dies
with ``got Future <...> attached to a different loop`` / ``Event loop is closed``.
Diagnosed 2026-08-27 from ``dispatch_due_leads`` / ``sweep_stale_*`` crash-looping every
beat tick while the pool cycled stale connections.

Fix: one long-lived event loop per worker process, running on a dedicated daemon
thread. Every task coroutine runs on that single loop, so the engine's pool stays
valid for the life of the process. Handing the coroutine to another thread also means
this works unchanged when the caller already has a running loop — CELERY_TASK_ALWAYS_EAGER
(the solo-dev mode in RUN.md) dispatches ``.delay()`` synchronously from inside the
async FastAPI route that called it.
"""

import asyncio
import threading
from collections.abc import Coroutine
from typing import Any

_loop: asyncio.AbstractEventLoop | None = None
_lock = threading.Lock()


def _ensure_loop() -> asyncio.AbstractEventLoop:
    global _loop
    with _lock:
        if _loop is not None and not _loop.is_closed():
            return _loop
        loop = asyncio.new_event_loop()
        threading.Thread(target=loop.run_forever, name="worker-async-bridge", daemon=True).start()
        _loop = loop
        return loop


def run_sync[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run ``coro`` to completion on the worker's shared event loop, returning its result."""
    loop = _ensure_loop()
    return asyncio.run_coroutine_threadsafe(coro, loop).result()
