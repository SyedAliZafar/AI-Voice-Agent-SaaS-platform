"""Tests for backend/tools/base.py's shared uncertain_result helper (outliers.md §5)."""

from backend.tools.base import uncertain_result


def test_status_is_uncertain_not_error():
    """Deliberately not shaped like {"error": ...} — that shape reads as "this failed"
    to both the model and anyone debugging the CallEvent audit trail later."""
    result = uncertain_result("booking")
    assert result["status"] == "uncertain"
    assert "error" not in result


def test_instruction_forbids_confirming_either_outcome():
    result = uncertain_result("reschedule")
    instruction = result["instruction"].lower()
    assert "reschedule" in instruction
    assert "not tell the caller it worked" in instruction
    assert "not tell the caller it failed" in instruction
