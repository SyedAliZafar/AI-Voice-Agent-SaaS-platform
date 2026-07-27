"""Tool: create_lead — creates a new CRM lead/contact from call data."""

from typing import Any

from backend.services.integration_service import create_hubspot_contact
from backend.tools.base import BaseTool


class CreateLeadTool(BaseTool):
    name = "create_lead"
    description = "Create a new lead in the CRM with the caller's contact details and notes."
    input_schema = {
        "type": "object",
        "properties": {
            "email": {"type": "string"},
            "phone": {"type": "string"},
            "notes": {"type": "string", "description": "Summary of what the caller wants"},
        },
        "required": ["phone", "notes"],
    }

    async def handler(self, input: dict, caller_context: dict[str, Any]) -> dict:
        result = await create_hubspot_contact(
            email=input.get("email", ""),
            phone=input["phone"],
            notes=input["notes"],
            api_key=caller_context.get("crm_api_key", ""),
        )
        return {"created": True, "contact_id": result.get("id")}
