"""Extracts tenant_id from the JWT and makes it available to request handlers.

ADR-001: row-level tenant isolation. Every DB query in services/ should
filter by tenant_id — this middleware is what makes that value trustworthy
(never accept a client-supplied tenant_id from query params in production).
"""

from fastapi import Request
from jose import jwt

from backend.config import get_settings

settings = get_settings()


async def tenant_middleware(request: Request, call_next):
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.removeprefix("Bearer ")
        try:
            payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
            request.state.tenant_id = payload.get("tenant_id")
            request.state.user_id = payload.get("sub")
        except jwt.JWTError:
            request.state.tenant_id = None

    response = await call_next(request)
    return response
