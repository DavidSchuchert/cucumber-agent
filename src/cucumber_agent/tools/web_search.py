"""Web search tool — DuckDuckGo (no API key required)."""

from __future__ import annotations

import httpx

from cucumber_agent.tools.base import BaseTool, ToolResult
from cucumber_agent.tools.registry import ToolRegistry


class WebSearchTool(BaseTool):
    """Search the web using DuckDuckGo instant answers."""

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
                "description": "Die Suchanfrage auf Englisch oder Deutsch.",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximale Anzahl Ergebnisse (Standard: 5).",
            },
        },
        "required": ["query"],
    }

    async def execute(self, query: str, max_results: int = 5) -> ToolResult:
        """Search DuckDuckGo instant answer API."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Instant answer JSON API
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

            # Main abstract
            if data.get("Abstract"):
                source = data.get("AbstractSource", "")
                url = data.get("AbstractURL", "")
                results.append(
                    f"📋 **{data.get('Heading', query)}**\n"
                    f"{data['Abstract']}\n"
                    f"Quelle: {source} — {url}"
                )

            # Direct answer (e.g. for calculations, conversions)
            if data.get("Answer"):
                results.append(f"✅ **Direkte Antwort:** {data['Answer']}")

            # Related topics
            for topic in data.get("RelatedTopics", [])[:max_results]:
                if isinstance(topic, dict) and topic.get("Text"):
                    url = topic.get("FirstURL", "")
                    text = topic["Text"][:200]
                    results.append(f"• {text}\n  {url}")
                elif isinstance(topic, dict) and topic.get("Topics"):
                    # Nested category
                    for sub in topic["Topics"][:2]:
                        if isinstance(sub, dict) and sub.get("Text"):
                            results.append(f"• {sub['Text'][:200]}")

            # Direct results
            for r in data.get("Results", [])[:3]:
                if r.get("Text"):
                    results.append(f"• {r['Text'][:200]}\n  {r.get('FirstURL', '')}")

            if results:
                return ToolResult(
                    success=True,
                    output="\n\n".join(results[:max_results]),
                )

            return ToolResult(
                success=True,
                output=(
                    f"Keine Instant-Ergebnisse für '{query}' gefunden.\n"
                    "Tipp: Formuliere die Suche auf Englisch oder präziser."
                ),
            )

        except httpx.TimeoutException:
            return ToolResult(success=False, output="", error="Web-Suche Timeout (10s).")
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


# Register the tool
ToolRegistry.register(WebSearchTool())
