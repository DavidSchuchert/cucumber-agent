"""Shell execution tool."""

from __future__ import annotations

import asyncio

from cucumber_agent.tools.base import BaseTool, ToolResult
from cucumber_agent.tools.registry import ToolRegistry


class ShellTool(BaseTool):
    """Execute shell commands with user approval."""

    name = "shell"
    description = "Execute a shell command. ALWAYS ask user for approval before running."
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute",
            },
            "reason": {
                "type": "string",
                "description": "Brief explanation of what this command does",
            },
            "working_dir": {
                "type": "string",
                "description": "Optional working directory",
            },
        },
        "required": ["command"],
    }

    async def execute(
        self, command: str, reason: str = "", working_dir: str | None = None
    ) -> ToolResult:
        """Execute a shell command."""
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
            )
            stdout, stderr = await process.communicate()

            output = stdout.decode() if stdout else ""
            error = stderr.decode() if stderr else ""

            if process.returncode != 0:
                return ToolResult(success=False, output=output, error=error)

            return ToolResult(success=True, output=output)
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


# Register the tool
ToolRegistry.register(ShellTool())
