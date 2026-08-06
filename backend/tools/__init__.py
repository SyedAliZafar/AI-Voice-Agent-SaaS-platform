"""Tool registry — add new tools here and they're automatically available
to every agent's DeepSeek conversation.
"""

from collections.abc import Callable, Coroutine
from typing import Any

from backend.tools.base import BaseTool
from backend.tools.book_appointment import BookAppointmentTool
from backend.tools.check_availability import CheckAvailabilityTool
from backend.tools.create_lead import CreateLeadTool
from backend.tools.lookup_customer import LookupCustomerTool
from backend.tools.send_sms import SendSmsTool
from backend.tools.transfer_call import TransferCallTool

_REGISTRY: dict[str, BaseTool] = {
    tool.name: tool
    for tool in [
        CheckAvailabilityTool(),
        BookAppointmentTool(),
        LookupCustomerTool(),
        CreateLeadTool(),
        TransferCallTool(),
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
