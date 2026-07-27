"""Tool: lookup_customer — checks CRM for an existing customer record by phone."""

from typing import Any

from backend.tools.base import BaseTool


class LookupCustomerTool(BaseTool):
    name = "lookup_customer"
    description = "Look up an existing customer record by phone number."
    input_schema = {
        "type": "object",
        "properties": {
            "phone_number": {"type": "string", "description": "Customer's phone number"},
        },
        "required": ["phone_number"],
    }

    async def handler(self, input: dict, caller_context: dict[str, Any]) -> dict:
        # Wire up your CRM's lookup API here (HubSpot search, Salesforce SOQL, etc)
        return {"found": False, "customer": None}
