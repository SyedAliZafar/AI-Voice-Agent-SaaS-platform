"""Schemas for the voice platform's phone number roster.

Separate from schemas/agent.py's Platform* models even though both describe things
living on the platform rather than in our database: a number is its own resource with
its own router, and the local `PhoneNumber` model (models/agent.py) will eventually want
request/response shapes here too.
"""

from pydantic import BaseModel


class PlatformPhoneNumber(BaseModel):
    """One number as the platform reports it right now — not persisted.

    `inbound_agent_id`/`outbound_agent_id` are the platform's own agent ids, null when
    nothing is assigned. That null is the useful signal: a number with neither is paid
    for and answers nothing.
    """

    number: str
    # Platform-formatted for display, falling back to `number` — never blank, which
    # `nickname` can be.
    pretty: str
    nickname: str | None = None
    inbound_agent_id: str | None = None
    outbound_agent_id: str | None = None
    last_modified_ms: int | None = None


class PlatformPhoneNumbersResponse(BaseModel):
    platform: str
    numbers: list[PlatformPhoneNumber]
