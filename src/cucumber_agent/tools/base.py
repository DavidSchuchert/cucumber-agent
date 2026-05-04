"""Base classes for tools."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass


@dataclass
class ToolResult:
    """Result from a tool execution."""

    success: bool
    output: str
    error: str | None = None


class BaseTool:
    """Base class for all tools."""

    name: str
    description: str
    parameters: dict  # JSON Schema for tool parameters
    auto_approve: bool = False  # If True, executes without user confirmation
    execute: Callable[..., Awaitable[ToolResult]]

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
