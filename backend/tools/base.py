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
