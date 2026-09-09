"""Pydantic schemas for serial, event-chained batch outreach runs.

See backend/models/batch_run.py and phases/in-progress/serial-batch-calling.md for the
design: one call in flight at a time, the next dialed only once the previous reaches a
terminal state, not on a fixed timer.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class BatchRunRequest(BaseModel):
    """Start a serial batch run. Same agent-source rule and target-selection knobs as
    BatchCallRequest (backend/schemas/prospect.py) — this is that endpoint's paced
    sibling, not a replacement; see that schema's docstring for why local vs.
    platform-agent calling differ.

    `prospect_ids` is the difference from /batch-call: hand it the exact prospects the
    operator ticked and those get called, in that order. Leave it empty and the
    `limit`/`city`/`max_call_count` filters pick the targets instead, exactly as
    /batch-call does. When it's supplied the filters are ignored — see
    batch_service.start_run.
    """

    agent_id: uuid.UUID | None = None
    external_agent_id: str | None = None
    prospect_ids: list[uuid.UUID] = Field(default_factory=list, max_length=15)
    limit: int = Field(default=10, ge=1, le=15)
    city: str | None = None
    max_call_count: int = Field(default=0, ge=0)
    # Applied to every call in the run. Placeholders that vary per prospect
    # (company_name, phone_number, city, industry) are filled from each prospect at dial
    # time and override anything supplied here — see batch_service._variables_for.
    dynamic_variables: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _exactly_one_agent(self) -> "BatchRunRequest":
        if (self.agent_id is None) == (self.external_agent_id is None):
            raise ValueError("provide exactly one of agent_id or external_agent_id")
        return self


class BatchRunItemResponse(BaseModel):
    prospect_id: uuid.UUID
    name: str
    position: int
    status: str  # queued | dialing | done | skipped
    call_id: uuid.UUID | None
    skip_reason: str | None

    model_config = {"from_attributes": True}


class BatchRunResponse(BaseModel):
    id: uuid.UUID
    status: str  # running | done | cancelled | failed
    total: int
    started_at: datetime
    finished_at: datetime | None
    items: list[BatchRunItemResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}
