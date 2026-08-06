"""Base class for LLM-callable tools.

Every tool exposes: a name, a JSON schema (for the LLM's tool definitions),
and an async handler(input, caller_context) -> dict.
"""

from abc import ABC, abstractmethod
from typing import Any


class BaseTool(ABC):
    name: str
    description: str
    input_schema: dict

    @abstractmethod
    async def handler(self, input: dict, caller_context: dict[str, Any]) -> dict:
        """Execute the tool. Return a dict — it gets str()'d back to the LLM."""
        ...

    def to_definition(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


def uncertain_result(action: str) -> dict[str, Any]:
    """The tool result for a side-effecting request that timed out before a response
    arrived — see integration_service.IntegrationTimeoutError for why this must NOT be
    shaped like {"error": ...}.

    A live call on 2026-08-06 (outliers.md §5) showed a bare error result isn't enough:
    a reschedule timed out, the tool returned a generic error, and the model told the
    caller it succeeded anyway — true that time by luck (Cal.com had processed the
    request before our client gave up waiting), but nothing about the result actually
    confirmed that. "status": "uncertain" — not "error" — makes the distinction survive
    at a glance in the CallEvent audit trail too, not just in prose the model has to
    parse carefully under time pressure mid-call. Also deliberately excluded from the
    ADR-009 §4c ledger (retell_ws._ledger_entry) — an unconfirmed outcome must not be
    recorded as completed, and a caller retrying it must not be blocked as a duplicate.
    """
    return {
        "status": "uncertain",
        "instruction": (
            f"The {action} request timed out before Cal.com confirmed the outcome. This "
            f"is NOT a confirmed failure and NOT a confirmed success — do not tell the "
            f"caller it worked, and do not tell the caller it failed. Tell them you'll "
            f"double-check and follow up shortly."
        ),
    }
