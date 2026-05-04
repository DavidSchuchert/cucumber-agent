"""Tool registry."""

from __future__ import annotations

from cucumber_agent.tools.base import BaseTool, ToolResult


class ToolRegistry:
    """Registry for available tools."""

    _tools: dict[str, BaseTool] = {}

    @classmethod
    def register(cls, tool: BaseTool) -> None:
        """Register a tool."""
        cls._tools[tool.name] = tool

    @classmethod
    def unregister(cls, name: str) -> None:
        """Unregister a tool."""
        cls._tools.pop(name, None)

    @classmethod
    def get(cls, name: str) -> BaseTool | None:
        """Get a tool by name."""
        return cls._tools.get(name)

    @classmethod
    def list_tools(cls) -> list[str]:
        """List all registered tool names."""
        return list(cls._tools.keys())

    @classmethod
    def get_capabilities_summary(cls) -> list[dict[str, str]]:
        """Return a list of tool names and their descriptions."""
        return [
            {"name": tool.name, "description": tool.description}
            for tool in cls._tools.values()
        ]

    @classmethod
    def get_tools_spec(cls, provider: str = "openrouter") -> list[dict]:
        """Get specifications for all registered tools for a specific provider."""
        return [tool.get_spec(provider) for tool in cls._tools.values()]

    @classmethod
    async def execute(cls, name: str, **kwargs) -> ToolResult:
        """Execute a tool by name."""
        tool = cls.get(name)
        if not tool:
            return ToolResult(success=False, output="", error=f"Unknown tool: {name}")
        return await tool.execute(**kwargs)
