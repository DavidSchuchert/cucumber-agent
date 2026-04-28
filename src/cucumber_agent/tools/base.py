"""Base classes for tools."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ToolResult:
    """Result from a tool execution."""

    success: bool
    output: str
    error: str | None = None


class BaseTool(ABC):
    """Base class for all tools."""

    name: str
    description: str
    parameters: dict  # JSON Schema for tool parameters

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """Execute the tool with given parameters."""
        ...

    def get_spec(self, provider: str = "openrouter") -> dict:
        """Get provider-specific tool specification."""
        # MiniMax now uses the OpenAI-compatible v1 endpoint, so all use the same format
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

