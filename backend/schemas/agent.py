"""Pydantic schemas for agent CRUD."""

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")


class AgentCreate(BaseModel):
    name: str
    system_prompt: str = ""
    voice_config: dict = Field(default_factory=dict)
    platform: str = "retell"
    use_custom_llm: bool = False


class AgentUpdate(BaseModel):
    name: str | None = None
    system_prompt: str | None = None
    voice_config: dict | None = None
    use_custom_llm: bool | None = None


class AgentResponse(BaseModel):
    id: uuid.UUID
    name: str
    system_prompt: str
    voice_config: dict
    platform: str
    use_custom_llm: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class TestCallRequest(BaseModel):
    to_number: str

    @field_validator("to_number")
    @classmethod
    def validate_e164(cls, value: str) -> str:
        if not E164_RE.match(value):
            raise ValueError("to_number must be in E.164 format, e.g. +491701234567")
        return value


class TestCallResponse(BaseModel):
    call_id: str
    from_number: str
    status: str
