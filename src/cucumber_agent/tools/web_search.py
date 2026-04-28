"""Web search tool — MiniMax API with DuckDuckGo fallback."""

from __future__ import annotations

import httpx

from cucumber_agent.tools.base import BaseTool, ToolResult
from cucumber_agent.tools.registry import ToolRegistry


class WebSearchTool(BaseTool):
    """Search the web using MiniMax API or DuckDuckGo fallback."""

    name = "web_search"
    description = (
        "Sucht im Internet nach aktuellen Informationen. "
        "Nutze dieses Tool wenn der Benutzer nach aktuellen Fakten, "
        "Nachrichten, Dokumentation oder unbekannten Themen fragt."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Die Suchanfrage (auf Englisch für beste Ergebnisse).",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximale Anzahl Ergebnisse (Standard: 5).",
            },
        },
        "required": ["query"],
    }

    async def execute(self, query: str, max_results: int = 5) -> ToolResult:
        """Search the web using MiniMax API or DuckDuckGo fallback."""
        import os

        api_key = os.environ.get("MINIMAX_API_KEY")

        if api_key:
            return await self._minimax_search(query, max_results, api_key)
        else:
            return await self._duckduckgo_search(query, max_results)

    async def _minimax_search(self, query: str, max_results: int, api_key: str) -> ToolResult:
        """Search using MiniMax API (MCP protocol)."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "https://api.minimax.io/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "MiniMax-M2.7",
                        "messages": [
                            {
                                "role": "user",
                                "content": f"Search the web for: {query}\n\n"
                                           f"Return the search results with titles, snippets, and URLs. "
                                           f"Max {max_results} results."
                            }
                        ],
                        "max_tokens": 1000,
                    }
                )
                resp.raise_for_status()
                data = resp.json()

            choices = data.get("choices", [{}])
            content = choices[0].get("message", {}).get("content", "")
            if content:
                return ToolResult(success=True, output=content)
            else:
                return ToolResult(success=True, output="Keine Suchergebnisse erhalten.")

        except httpx.TimeoutException:
            return ToolResult(success=False, output="", error="MiniMax Web-Suche Timeout (30s).")
        except Exception as e:
            # Fall back to DuckDuckGo on error
            return await self._duckduckgo_search(query, max_results)

    async def _duckduckgo_search(self, query: str, max_results: int) -> ToolResult:
        """Search using DuckDuckGo instant answer API (fallback/no API key)."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://api.duckduckgo.com/",
                    params={
                        "q": query,
                        "format": "json",
                        "no_redirect": "1",
                        "no_html": "1",
                        "skip_disambig": "1",
                    },
                    headers={"User-Agent": "CucumberAgent/1.0"},
                )
                resp.raise_for_status()
                data = resp.json()

            results: list[str] = []

            if data.get("Abstract"):
                source = data.get("AbstractSource", "")
                url = data.get("AbstractURL", "")
                results.append(
                    f"📋 **{data.get('Heading', query)}**\n"
                    f"{data['Abstract']}\n"
                    f"Quelle: {source} — {url}"
                )

            if data.get("Answer"):
                results.append(f"✅ **Direkte Antwort:** {data['Answer']}")

            for topic in data.get("RelatedTopics", [])[:max_results]:
                if isinstance(topic, dict) and topic.get("Text"):
                    url = topic.get("FirstURL", "")
                    text = topic["Text"][:200]
                    results.append(f"• {text}\n  {url}")
                elif isinstance(topic, dict) and topic.get("Topics"):
                    for sub in topic["Topics"][:2]:
                        if isinstance(sub, dict) and sub.get("Text"):
                            results.append(f"• {sub['Text'][:200]}")

            for r in data.get("Results", [])[:3]:
                if r.get("Text"):
                    results.append(f"• {r['Text'][:200]}\n  {r.get('FirstURL', '')}")

            if results:
                return ToolResult(success=True, output="\n\n".join(results[:max_results]))

            return ToolResult(
                success=True,
                output=f"Keine Ergebnisse für '{query}' gefunden.",
            )

        except httpx.TimeoutException:
            return ToolResult(success=False, output="", error="Web-Suche Timeout (10s).")
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


# Register the tool
ToolRegistry.register(WebSearchTool())
