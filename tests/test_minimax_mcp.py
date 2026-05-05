"""Tests for MiniMax Token Plan MCP integration."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from conftest import make_config

from cucumber_agent.config import ProviderConfig
from cucumber_agent.minimax_mcp import (
    MiniMaxMCPError,
    _normalize_api_host,
    build_minimax_mcp_config,
    extract_mcp_text,
    minimax_mcp_mode,
    should_use_minimax_mcp,
)


def test_normalize_api_host_strips_compat_suffixes():
    assert _normalize_api_host("https://api.minimax.io/v1") == "https://api.minimax.io"
    assert _normalize_api_host("https://api.minimax.io/anthropic") == "https://api.minimax.io"


def test_minimax_mcp_mode_aliases(monkeypatch):
    monkeypatch.setenv("CUCUMBER_MINIMAX_MCP", "1")
    assert minimax_mcp_mode() == "always"
    monkeypatch.setenv("CUCUMBER_MINIMAX_MCP", "off")
    assert minimax_mcp_mode() == "never"


def test_build_minimax_mcp_config_uses_provider_config(tmp_path, monkeypatch):
    cfg = make_config(tmp_path)
    cfg.providers["minimax"] = ProviderConfig(
        name="minimax",
        api_key="test-key",
        base_url="https://api.minimax.io/v1",
    )
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.delenv("MINIMAX_API_HOST", raising=False)

    mcp_config = build_minimax_mcp_config(cfg)

    assert mcp_config.command == "uvx"
    assert mcp_config.args == ("minimax-coding-plan-mcp", "-y")
    assert mcp_config.env["MINIMAX_API_KEY"] == "test-key"
    assert mcp_config.env["MINIMAX_API_HOST"] == "https://api.minimax.io"


def test_build_minimax_mcp_config_requires_api_key(tmp_path, monkeypatch):
    cfg = make_config(tmp_path)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)

    with pytest.raises(MiniMaxMCPError, match="MINIMAX_API_KEY"):
        build_minimax_mcp_config(cfg)


def test_should_use_minimax_mcp_auto_requires_minimax_provider(tmp_path, monkeypatch):
    cfg = make_config(tmp_path)
    cfg.providers["minimax"] = ProviderConfig(name="minimax", api_key="test-key")
    cfg.agent.provider = "openrouter"
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
    monkeypatch.setenv("CUCUMBER_MINIMAX_MCP", "auto")

    with patch("cucumber_agent.minimax_mcp.minimax_mcp_command_available", return_value=True):
        assert should_use_minimax_mcp(cfg) is False

    cfg.agent.provider = "minimax"
    with patch("cucumber_agent.minimax_mcp.minimax_mcp_command_available", return_value=True):
        assert should_use_minimax_mcp(cfg) is True


def test_extract_mcp_text_flattens_text_blocks():
    result = {"content": [{"type": "text", "text": "hello"}, {"type": "text", "text": "world"}]}
    assert extract_mcp_text(result) == "hello\nworld"


def test_extract_mcp_text_raises_on_tool_error():
    with pytest.raises(MiniMaxMCPError, match="bad image"):
        extract_mcp_text({"isError": True, "content": [{"type": "text", "text": "bad image"}]})
