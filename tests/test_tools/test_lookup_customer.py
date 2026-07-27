"""Tests for the lookup_customer tool handler."""

import pytest

from backend.tools.lookup_customer import LookupCustomerTool


@pytest.mark.asyncio
async def test_lookup_customer_not_found_by_default():
    tool = LookupCustomerTool()
    result = await tool.handler(
        input={"phone_number": "+15551234567"}, caller_context={}
    )
    assert result == {"found": False, "customer": None}


def test_tool_requires_phone_number():
    tool = LookupCustomerTool()
    definition = tool.to_definition()
    assert definition["input_schema"]["required"] == ["phone_number"]
