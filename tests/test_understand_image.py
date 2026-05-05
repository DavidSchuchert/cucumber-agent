"""Tests for understand_image tool routing."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from cucumber_agent.minimax_mcp import MiniMaxMCPError
from cucumber_agent.tools.understand_image import UnderstandImageTool


@pytest.mark.asyncio
async def test_understand_image_uses_minimax_mcp():
    tool = UnderstandImageTool()
    with (
        patch("cucumber_agent.tools.understand_image.can_try_minimax_mcp", return_value=True),
        patch(
            "cucumber_agent.tools.understand_image.call_minimax_mcp_tool",
            new=AsyncMock(return_value="A screenshot with a login form."),
        ) as call_mcp,
    ):
        result = await tool.execute(
            prompt="Beschreibe das Bild",
            image_url="https://example.com/screen.png",
        )

    assert result.success is True
    assert "login form" in result.output
    call_mcp.assert_awaited_once_with(
        "understand_image",
        {"prompt": "Beschreibe das Bild", "image_url": "https://example.com/screen.png"},
    )


@pytest.mark.asyncio
async def test_understand_image_forced_mcp_error(monkeypatch):
    monkeypatch.setenv("CUCUMBER_MINIMAX_MCP", "always")
    tool = UnderstandImageTool()
    with (
        patch("cucumber_agent.tools.understand_image.can_try_minimax_mcp", return_value=True),
        patch(
            "cucumber_agent.tools.understand_image.call_minimax_mcp_tool",
            new=AsyncMock(side_effect=MiniMaxMCPError("bad key")),
        ),
    ):
        result = await tool.execute(
            prompt="Beschreibe das Bild",
            image_url="https://example.com/screen.png",
        )

    assert result.success is False
    assert "MiniMax MCP understand_image fehlgeschlagen" in (result.error or "")
    assert "bad key" in (result.error or "")


@pytest.mark.asyncio
async def test_understand_image_validates_local_file(tmp_path):
    text_file = Path(tmp_path / "note.txt")
    text_file.write_text("not an image", encoding="utf-8")
    tool = UnderstandImageTool()

    result = await tool.execute(prompt="Beschreibe", image_url=str(text_file))

    assert result.success is False
    assert "Unsupported image format" in (result.error or "")
