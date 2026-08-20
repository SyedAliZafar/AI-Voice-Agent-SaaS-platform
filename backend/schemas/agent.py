"""Pydantic schemas for agent CRUD."""

import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from backend.services import llm_service

E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")


def _validate_e164(value: str) -> str:
    """Shared by every schema that carries a number we will actually dial, so the two
    dial paths (local agent, platform-native agent) can't drift on what they accept."""
    if not E164_RE.match(value):
        raise ValueError("to_number must be in E.164 format, e.g. +491701234567")
    return value


def _validate_llm_model(value: str) -> str:
    """ "" is valid (means "use settings.default_llm_model"). Otherwise the model's
    *provider* must be resolvable — deliberately not "must have a configured key",
    so an agent can be set to a model before that provider's API key exists.
    """
    if value:
        try:
            llm_service.provider_for(value)
        except llm_service.LLMConfigError as exc:
            raise ValueError(str(exc)) from exc
    return value


class AgentCreate(BaseModel):
    name: str
    system_prompt: str = ""
    voice_config: dict = Field(default_factory=dict)
    platform: str = "retell"
    use_custom_llm: bool = False
    llm_model: str = ""

    _validate_llm_model = field_validator("llm_model")(_validate_llm_model)


class AgentUpdate(BaseModel):
    name: str | None = None
    system_prompt: str | None = None
    voice_config: dict | None = None
    use_custom_llm: bool | None = None
    llm_model: str | None = None

    @field_validator("llm_model")
    @classmethod
    def _validate_llm_model_update(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _validate_llm_model(value)


class AgentResponse(BaseModel):
    id: uuid.UUID
    name: str
    system_prompt: str
    voice_config: dict
    platform: str
    use_custom_llm: bool
    llm_model: str
    created_at: datetime

    model_config = {"from_attributes": True}


class LlmModelInfo(BaseModel):
    id: str
    label: str
    provider: str
    configured: bool  # whether the provider's API key is currently set


class LlmModelsResponse(BaseModel):
    models: list[LlmModelInfo]
    default: str


class AmbientSoundInfo(BaseModel):
    id: str
    label: str


class AmbientSoundsResponse(BaseModel):
    options: list[AmbientSoundInfo]
    # Whether the tenant's own campaigns have no per-agent override (voice_config has no
    # "ambientSound" key) rather than an explicit choice — distinct from "off", which is
    # an explicit `null` override the frontend can tell apart via the agent's own
    # voice_config, not this field. This is only the fleet-wide fallback every agent
    # inherits unless it overrides.
    default: str | None


class SandboxMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class SandboxChatRequest(BaseModel):
    # Capped so a runaway client can't send an unbounded prompt — the sandbox is a
    # stateless request/response API, the client resends the whole history each turn.
    messages: list[SandboxMessage] = Field(min_length=1, max_length=50)
    system_prompt_override: str | None = None
    model: str | None = None
    tools_enabled: bool = False

    @field_validator("model")
    @classmethod
    def _validate_model(cls, value: str | None) -> str | None:
        if value:
            return _validate_llm_model(value)
        return value


class SandboxChatResponse(BaseModel):
    reply: str
    model: str
    tools_enabled: bool
    # The exact system prompt this turn ran against — lets a sandbox UI show the
    # operator what was actually sent, rather than the client reconstructing an
    # approximation of it client-side. Always populated (agent.system_prompt when no
    # override was given).
    system_prompt: str


class TestCallRequest(BaseModel):
    to_number: str

    _validate_to_number = field_validator("to_number")(_validate_e164)


class TestCallResponse(BaseModel):
    call_id: str
    from_number: str
    status: str


class PlatformAgentInfo(BaseModel):
    """One agent as it exists on the voice platform itself (ADR-012).

    Read-only and not persisted — this mirrors whatever the platform reports right now,
    which is why there's no local `id` here. `external_id` is the platform's own id and
    the only handle a dial request needs.
    """

    external_id: str
    name: str
    voice_id: str | None = None
    # Platform response-engine kind ("retell-llm", "custom-llm", "conversation-flow").
    # Surfaced so an operator can see whether an agent runs on the platform's own brain
    # before dialing it.
    engine: str | None = None
    version: int | None = None
    last_modified_ms: int | None = None


class PlatformAgentsResponse(BaseModel):
    platform: str
    agents: list[PlatformAgentInfo]


class PlatformAgentVariablesResponse(BaseModel):
    """The `{{placeholder}}` names a platform agent's prompt declares (ADR-012) — what
    must be filled in before it can be dialed. Empty for an agent whose prompt uses none,
    and also for one whose prompt we can't read (custom-llm / conversation-flow), which
    are deliberately indistinguishable here: both mean "nothing for you to fill in"."""

    external_agent_id: str
    variables: list[str]


class PlatformAgentCallRequest(BaseModel):
    external_agent_id: str
    to_number: str
    platform: str = "retell"
    # Fills the agent prompt's {{placeholders}} for this call only. Every name the prompt
    # declares must be present and non-blank — test_call_service refuses the dial
    # otherwise, since Retell speaks an unfilled placeholder verbatim.
    dynamic_variables: dict[str, str] = Field(default_factory=dict)

    _validate_to_number = field_validator("to_number")(_validate_e164)


class PlatformAgentCallResponse(BaseModel):
    call_id: str
    from_number: str
    status: str
    # Echoed back from the platform's roster so the UI can confirm *which* agent it
    # actually reached — the request carries an opaque id, and confirming by name is how
    # an operator catches having picked the wrong one.
    agent_name: str
