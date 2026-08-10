"""Tests for the flag_for_human_review tool handler."""

import pytest

from backend.tools.flag_for_human_review import FlagForHumanReviewTool


@pytest.mark.asyncio
async def test_flag_for_human_review_returns_flagged_result():
    tool = FlagForHumanReviewTool()

    result = await tool.handler(
        input={"reason": "Caller asked about financing credit checks for solar installs"},
        caller_context={},
    )

    assert result == {
        "flagged": True,
        "reason": "Caller asked about financing credit checks for solar installs",
    }


def test_flag_for_human_review_definition():
    tool = FlagForHumanReviewTool()
    definition = tool.to_definition()

    assert definition["name"] == "flag_for_human_review"
    assert set(definition["input_schema"]["required"]) == {"reason"}
