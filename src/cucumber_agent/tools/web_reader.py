"""Tool to read the content of a web page and convert it to markdown."""

from __future__ import annotations

import httpx
import trafilatura
from cucumber_agent.tools.base import BaseTool, ToolResult
from cucumber_agent.tools.registry import ToolRegistry


class WebReaderTool(BaseTool):
    """Read a specific URL and extract its main content as markdown."""

    name = "web_reader"
    description = (
        "Extract the main text content from a specific URL. "
        "Use this when you have a specific URL to read, "
        "rather than searching for information."
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL of the web page to read.",
            },
            "reason": {
                "type": "string",
                "description": "The reason why you need to read this URL.",
            },
        },
        "required": ["url"],
    }

    async def execute(self, url: str, reason: str = "") -> ToolResult:
        """Execute the web reader tool."""
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                }
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                
                html = response.text
                
                # Extract main content using trafilatura
                # include_links=True to keep references, include_formatting=True for headers/bold/etc
                content = trafilatura.extract(
                    html, 
                    include_links=True, 
                    include_formatting=True,
                    output_format="markdown",
                    favor_precision=True
                )
                
                if not content:
                    return ToolResult(
                        success=False,
                        output="",
                        error="Could not extract meaningful content from the page. It might be empty or protected."
                    )

                # Truncate if extremely long to save tokens (approx 15k tokens limit)
                if len(content) > 50000:
                    content = content[:50000] + "\n\n[... content truncated due to length ...]"

                return ToolResult(success=True, output=content)

        except httpx.HTTPStatusError as e:
            return ToolResult(
                success=False,
                output="",
                error=f"HTTP error {e.response.status_code}: {e.response.reason_phrase}"
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Failed to read URL: {str(e)}"
            )


# Register the tool
ToolRegistry.register(WebReaderTool())
