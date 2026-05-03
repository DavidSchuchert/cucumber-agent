"""Tests for web_search tool — DuckDuckGo HTML parsing."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cucumber_agent.tools.web_search import WebSearchTool, _extract_real_url, _strip_tags


def test_strip_tags_html_entities():
    assert _strip_tags("&amp;") == "&"
    # &lt;div&gt; is encoded text, not a tag — gets decoded to <div>
    assert _strip_tags("&lt;div&gt;") == "<div>"
    assert _strip_tags("&quot;hello&quot;") == '"hello"'
    assert _strip_tags("it&#39;s") == "it's"
    assert _strip_tags("a&nbsp;b") == "a b"
    # Actual HTML tags get stripped
    assert _strip_tags("<b>text</b>") == "text"


def test_strip_tags_removes_html():
    assert _strip_tags("<b>bold</b>") == "bold"
    assert _strip_tags("<a href='x'>link</a>") == "link"


def test_extract_real_url_ddg_redirect():
    ddg_url = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpage&rut=abc"
    assert _extract_real_url(ddg_url) == "https://example.com/page"


def test_extract_real_url_plain():
    assert _extract_real_url("https://example.com") == "https://example.com"


@pytest.mark.asyncio
async def test_web_search_returns_results():
    """Successful DDG response → results returned."""
    fake_html = """
    <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com">Python Docs</a>
    <a class="result__snippet" href="#">The official Python documentation.</a>
    """
    mock_response = MagicMock()
    mock_response.text = fake_html
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("cucumber_agent.tools.web_search.httpx.AsyncClient", return_value=mock_client):
        tool = WebSearchTool()
        result = await tool.execute(query="python docs", max_results=5)

    assert result.success
    assert "Python Docs" in result.output
    assert "example.com" in result.output


@pytest.mark.asyncio
async def test_web_search_no_results():
    """Empty HTML → graceful no-results message."""
    mock_response = MagicMock()
    mock_response.text = "<html><body>No results</body></html>"
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("cucumber_agent.tools.web_search.httpx.AsyncClient", return_value=mock_client):
        tool = WebSearchTool()
        result = await tool.execute(query="xyzzy404notfound", max_results=5)

    assert result.success
    assert "Keine Ergebnisse" in result.output
