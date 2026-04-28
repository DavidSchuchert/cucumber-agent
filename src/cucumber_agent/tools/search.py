"""Search tool - find files and directories."""

from __future__ import annotations

import os
from pathlib import Path

from cucumber_agent.tools.base import BaseTool, ToolResult
from cucumber_agent.tools.registry import ToolRegistry


class SearchTool(BaseTool):
    """Search for files and directories."""

    name = "search"
    description = "Search for files and directories. Use when user mentions a path or folder but you're not sure of the exact location."
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory to search in (default: home directory)",
            },
            "query": {
                "type": "string",
                "description": "Filename or directory name to search for",
            },
            "type": {
                "type": "string",
                "description": "Search type: 'file', 'dir', or 'all' (default: all)",
                "enum": ["file", "dir", "all"],
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results (default: 10)",
            },
        },
        "required": ["query"],
    }

    async def execute(
        self,
        query: str,
        path: str | None = None,
        type: str = "all",
        max_results: int = 10,
    ) -> ToolResult:
        """Search for files or directories."""
        try:
            search_root = Path(path) if path else Path.home()
            results = []

            # Search for matching names
            query_lower = query.lower()
            for root, dirs, files in os.walk(search_root):
                root_path = Path(root)

                # Check dirs
                if type in ("dir", "all"):
                    for d in dirs:
                        if query_lower in d.lower():
                            results.append(f"DIR: {root_path / d}")
                            if len(results) >= max_results:
                                break

                # Check files
                if type in ("file", "all"):
                    for f in files:
                        if query_lower in f.lower():
                            results.append(f"FILE: {root_path / f}")
                            if len(results) >= max_results:
                                break

                if len(results) >= max_results:
                    break

            if results:
                output = "\n".join(results[:max_results])
                return ToolResult(success=True, output=f"Found {len(results)} matches:\n{output}")
            else:
                return ToolResult(success=True, output=f"No matches found for '{query}'")

        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


# Register the tool
ToolRegistry.register(SearchTool())