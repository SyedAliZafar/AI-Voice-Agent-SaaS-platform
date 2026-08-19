"""Tool registry — add new tools here and they're automatically available
to every agent's DeepSeek conversation.

transfer_call is deliberately NOT registered. Its handler raises (there is no real
voice-platform transfer wired up yet — see tools/transfer_call.py and phase4.md), and
offering an unimplemented escape hatch to the model is worse than offering none: on call
b23851eb the agent, confused by its own fragmented replies, decided its audio was broken
and reached for transfer_call twice. Both raised, it had no fallback, and it spent the
rest of the call apologising for a fault that did not exist. flag_for_human_review is the
working escalation path until the transfer integration lands; re-add TransferCallTool
here the moment its handler does something real.
"""

from collections.abc import Callable, Coroutine
from typing import Any

from backend.tools.base import BaseTool
from backend.tools.book_appointment import BookAppointmentTool
from backend.tools.book_discovery_call import BookDiscoveryCallTool
from backend.tools.cancel_appointment import CancelAppointmentTool
from backend.tools.check_availability import CheckAvailabilityTool
from backend.tools.create_lead import CreateLeadTool
from backend.tools.flag_for_human_review import FlagForHumanReviewTool
from backend.tools.lookup_customer import LookupCustomerTool
from backend.tools.reschedule_appointment import RescheduleAppointmentTool
from backend.tools.send_sms import SendSmsTool

_REGISTRY: dict[str, BaseTool] = {
    tool.name: tool
    for tool in [
        CheckAvailabilityTool(),
        BookAppointmentTool(),
        BookDiscoveryCallTool(),
        CancelAppointmentTool(),
        RescheduleAppointmentTool(),
        LookupCustomerTool(),
        CreateLeadTool(),
        FlagForHumanReviewTool(),
        SendSmsTool(),
    ]
}


def get_tool_definitions() -> list[dict]:
    """Returns tool definitions in the shared {name, description, input_schema} shape."""
    return [tool.to_definition() for tool in _REGISTRY.values()]


def get_tool_handler(name: str) -> Callable[[dict, dict[str, Any]], Coroutine]:
    tool = _REGISTRY.get(name)
    if not tool:
        raise ValueError(f"Unknown tool: {name}")
    return tool.handler
