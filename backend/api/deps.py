"""Shared router dependencies — chiefly the trustworthy source of tenant_id.

ADR-001: row-level tenant isolation only holds if tenant_id can't be forged. Routers
must take it from Depends(get_current_tenant) and never from a client-supplied query
param, which is what the API did before this existed.

This is a dependency rather than middleware on purpose: BaseHTTPMiddleware can't raise
per-route 401s, can't participate in DI (so tests can't override it), and is skipped
entirely for WebSocket scopes — which matters for the Retell custom-LLM socket coming
next. It supersedes backend/middleware/tenant.py.

Webhook routes are deliberately NOT covered: Retell/Vapi can't send our JWT. Those need
platform signature verification instead — see the note in backend/api/webhooks.py.
"""

import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from backend.config import get_settings

settings = get_settings()

# auto_error=False so a missing header lands in our own 401 below rather than FastAPI's
# 403, and so the Authorize button still shows up in /docs.
bearer_scheme = HTTPBearer(auto_error=False)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_tenant(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> uuid.UUID:
    """Decode the bearer token and return its tenant_id claim.

    Raises 401 on anything short of a valid token carrying a well-formed tenant_id.
    Note the deliberate contrast with the old middleware, which swallowed decode
    errors and let the request continue with tenant_id unset.
    """
    if credentials is None:
        raise _unauthorized("Missing bearer token")

    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=["HS256"])
    except JWTError as exc:
        raise _unauthorized("Invalid or expired token") from exc

    raw_tenant_id = payload.get("tenant_id")
    if not raw_tenant_id:
        raise _unauthorized("Token is missing the tenant_id claim")

    try:
        return uuid.UUID(str(raw_tenant_id))
    except ValueError as exc:
        raise _unauthorized("Token tenant_id claim is not a valid UUID") from exc
