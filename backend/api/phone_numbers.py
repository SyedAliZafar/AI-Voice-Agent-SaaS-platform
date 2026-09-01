"""Phone numbers held on the voice platform account.

Read-only for now. The local `PhoneNumber` model (models/agent.py) exists but has never
had a CRUD surface — this router is where one belongs when it's needed, and until then
the honest answer to "what numbers do we have" is whatever the platform says right now,
not a row we wrote once and never revisited.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException

from backend.api.deps import get_current_tenant
from backend.schemas.phone_number import PlatformPhoneNumber, PlatformPhoneNumbersResponse
from backend.services import test_call_service

router = APIRouter()


@router.get("", response_model=PlatformPhoneNumbersResponse)
async def list_phone_numbers(
    platform: str = "retell",
    tenant_id: uuid.UUID = Depends(get_current_tenant),
):
    """The numbers this account can be reached on and dial from, fetched live.

    Mirrors GET /api/agents/platform exactly — same live-not-mirrored rule (ADR-012),
    same tenant caveat: `tenant_id` is required for auth but does not scope the result,
    because one RETELL_API_KEY serves the whole deployment today. Every tenant sees the
    same numbers until that key moves into per-tenant Integration storage.
    """
    try:
        numbers = await test_call_service.list_phone_numbers(platform)
    except test_call_service.TestCallError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:  # get_adapter on an unknown platform name
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PlatformPhoneNumbersResponse(
        platform=platform, numbers=[PlatformPhoneNumber(**n) for n in numbers]
    )
