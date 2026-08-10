"""Tests for the book_discovery_call tool handler."""

import pytest

from backend.tools.book_discovery_call import BookDiscoveryCallTool


@pytest.mark.asyncio
async def test_book_discovery_call_captures_info():
    tool = BookDiscoveryCallTool()

    result = await tool.handler(
        input={
            "name": "Jane Contractor",
            "phone": "+15551234567",
            "preferred_time": "Tomorrow afternoon",
        },
        caller_context={},
    )

    assert result == {
        "captured": True,
        "name": "Jane Contractor",
        "phone": "+15551234567",
        "preferred_time": "Tomorrow afternoon",
    }


def test_book_discovery_call_definition():
    tool = BookDiscoveryCallTool()
    definition = tool.to_definition()

    assert definition["name"] == "book_discovery_call"
    assert set(definition["input_schema"]["required"]) == {"name", "phone", "preferred_time"}
