"""Pydantic schemas for per-tenant integration settings (phase5 Session 1).

Masking lives here rather than in the service because it is purely a serialization
concern: the stored row genuinely holds the secret, and only the *response* must not.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

# Config keys whose values must never be echoed back to a client. A GET returning the
# key it was given is a needless way to leak it — a browser cache, a screenshot, or a
# proxy log is enough. Add to this set when a provider brings its own secret name.
SECRET_CONFIG_KEYS = frozenset({"api_key", "access_token", "refresh_token", "client_secret"})

_MASK = "•" * 8


def mask_secret(value: str) -> str:
    """Replace a secret with a fixed-width mask plus its last 4 characters.

    The tail is kept so an operator can tell *which* key is stored (useful when they have
    a sandbox and a production token) without it being reusable. Short values get no tail
    at all — for an 8-character secret, the last 4 is half of it.
    """
    if not value:
        return ""
    return f"{_MASK}{value[-4:]}" if len(value) > 8 else _MASK


def mask_config(config: dict[str, Any]) -> dict[str, Any]:
    return {
        key: mask_secret(str(value)) if key in SECRET_CONFIG_KEYS else value
        for key, value in config.items()
    }


class IntegrationUpsert(BaseModel):
    """PUT body. `config` MERGES into whatever is stored rather than replacing it, so a
    client that only wants to change the pipeline id doesn't have to re-send the API key
    (and a UI rendering the masked value back can't accidentally save the mask as the
    real secret). To clear one key, send it as an empty string.
    """

    kind: str = "crm"
    provider: str
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class IntegrationResponse(BaseModel):
    id: uuid.UUID
    kind: str
    provider: str
    config: dict[str, Any]  # secrets masked — see mask_config
    secrets_set: list[str]  # which SECRET_CONFIG_KEYS actually hold a value
    enabled: bool
    last_verified_at: datetime | None
    last_verify_error: str | None
    created_at: datetime

    @classmethod
    def from_model(cls, integration: Any) -> "IntegrationResponse":
        config = integration.config or {}
        return cls(
            id=integration.id,
            kind=integration.kind,
            provider=integration.provider,
            config=mask_config(config),
            secrets_set=sorted(k for k in SECRET_CONFIG_KEYS if config.get(k)),
            enabled=integration.enabled,
            last_verified_at=integration.last_verified_at,
            last_verify_error=integration.last_verify_error,
            created_at=integration.created_at,
        )


class IntegrationTestResult(BaseModel):
    """Outcome of POST /api/integrations/{kind}/test.

    `ok=False` is a 200 response, not an error status: "your HubSpot key is wrong" is a
    successful answer to "is my HubSpot key right?". The route only 4xxs when the request
    itself is bad (no such integration configured).
    """

    ok: bool
    provider: str
    detail: str
    checked_at: datetime
