"""Web search tool — DuckDuckGo HTML search."""

from __future__ import annotations

import re
from urllib.parse import unquote

import httpx

from cucumber_agent.tools.base import BaseTool, ToolResult
from cucumber_agent.tools.registry import ToolRegistry

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}

# Matches: <a class="result__a" href="URL">Title</a>  — attribute order varies across DDG versions
_TITLE_RE = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
    re.DOTALL,
)
# Matches: <a class="result__snippet" href="...">Snippet</a>
_SNIPPET_RE = re.compile(
    r'class="result__snippet"[^>]*>(.*?)</a>',
    re.DOTALL,
)


class WebSearchTool(BaseTool):
    """Search the web using DuckDuckGo."""

    name = "web_search"
    description = (
        "Sucht im Internet nach aktuellen Informationen. "
        "Nutze dieses Tool wenn der Benutzer nach aktuellen Fakten, "
        "Nachrichten, Dokumentation oder unbekannten Themen fragt."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Die Suchanfrage."},
            "max_results": {
                "type": "integer",
                "description": "Maximale Anzahl Ergebnisse (Standard: 5).",
            },
        },
        "required": ["query"],
    }

    async def execute(self, query: str, max_results: int = 5) -> ToolResult:
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                resp = await client.post(
                    "https://html.duckduckgo.com/html/",
                    data={"q": query, "kl": "de-de"},
                    headers=_HEADERS,
                )
                resp.raise_for_status()
                html = resp.text

            titles = _TITLE_RE.findall(html)
            snippets = [_strip_tags(s) for s in _SNIPPET_RE.findall(html)]

            results = []
            for i, (raw_url, raw_title) in enumerate(titles[:max_results]):
                url = _extract_real_url(raw_url)
                title = _strip_tags(raw_title)
                snippet = snippets[i] if i < len(snippets) else ""
                if title and url:
                    results.append({"title": title, "url": url, "snippet": snippet})

            if not results:
                return ToolResult(success=True, output=f"Keine Ergebnisse für '{query}'.")

            lines = [f"**Suchergebnisse: {query}**\n"]
            for i, r in enumerate(results, 1):
                lines.append(f"**{i}. {r['title']}**")
                if r["snippet"]:
                    lines.append(r["snippet"])
                lines.append(f"🔗 {r['url']}\n")

            return ToolResult(success=True, output="\n".join(lines))

        except Exception as e:
            return ToolResult(success=False, output="", error=f"Suche fehlgeschlagen: {e}")


def _strip_tags(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    return text.strip()


def _extract_real_url(url: str) -> str:
    """DuckDuckGo wraps URLs in redirects — extract the real destination."""
    m = re.search(r"uddg=([^&]+)", url)
    if m:
        return unquote(m.group(1))
    return url.strip()


ToolRegistry.register(WebSearchTool())
