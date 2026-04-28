"""CreateTool module - lets the agent generate its own custom python tools."""

from __future__ import annotations

from pathlib import Path

from cucumber_agent.tools.base import BaseTool, ToolResult
from cucumber_agent.tools.registry import ToolRegistry


class CreateToolTool(BaseTool):
    """Tool to create or update custom tools dynamically."""

    name = "create_tool"
    description = (
        "Creates or updates a custom Python tool that the agent can use immediately. "
        "The tool must subclass BaseTool. "
        "Make sure to implement the execute(self, **kwargs) -> ToolResult method."
    )
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "The name of the tool file (e.g. 'random_number')."
            },
            "code": {
                "type": "string",
                "description": (
                    "The complete Python code for the tool. "
                    "Must import BaseTool and ToolResult from cucumber_agent.tools.base."
                )
            }
        },
        "required": ["name", "code"],
    }

    async def execute(self, name: str, code: str) -> ToolResult:
        """Write the Python code to the custom_tools directory."""
        if not name.isidentifier():
            return ToolResult(
                success=False,
                output="",
                error="Tool name must be a valid Python identifier (no spaces, hyphens, etc).",
            )

        tools_dir = Path.home() / ".cucumber" / "custom_tools"
        tools_dir.mkdir(parents=True, exist_ok=True)
        
        file_path = tools_dir / f"{name}.py"
        
        try:
            file_path.write_text(code, encoding="utf-8")
            return ToolResult(
                success=True,
                output=f"Successfully created tool '{name}' at {file_path}. It will be hot-reloaded automatically.",
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Failed to write tool file: {e}",
            )

ToolRegistry.register(CreateToolTool())
