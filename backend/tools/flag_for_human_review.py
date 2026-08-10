"""Tool: flag_for_human_review — escalation fallback for whatever the caller raises that
isn't in the scripted objection bank (hvac-solar-outbound-knowledge-v1.md). No attempt to
handle the objection gracefully here — that's the prompt's job. The existing generic
CallEvent(event_type="tool_call") audit trail (llm_service._execute_tool_calls'
on_tool_event, wired in retell_ws.py) is the log — no new table or file needed for that,
same as book_discovery_call.
"""

from typing import Any

from backend.tools.base import BaseTool


class FlagForHumanReviewTool(BaseTool):
    name = "flag_for_human_review"
    description = (
        "Flag this call for human review when the caller raises an objection or "
        "question that isn't covered by the scripted objection bank. Do not attempt to "
        "improvise an answer instead — use this tool and move the conversation on."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": "What the caller raised that wasn't in the scripted objection bank",
            },
        },
        "required": ["reason"],
    }

    async def handler(self, input: dict, caller_context: dict[str, Any]) -> dict:
        return {
            "flagged": True,
            "reason": input["reason"],
        }
