"""Tests for provider system: OpenRouter, Ollama, DeepSeek, BaseProvider defaults."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from cucumber_agent.provider import BaseProvider, ModelResponse, ProviderRegistry
from cucumber_agent.providers.deepseek import DeepSeekProvider
from cucumber_agent.providers.ollama import OllamaProvider
from cucumber_agent.providers.openrouter import OpenRouterProvider
from cucumber_agent.session import Message, Role

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_response(status: int = 200, json_body: dict | None = None) -> MagicMock:
    """Build a minimal mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status
    resp.json = MagicMock(return_value=json_body or _default_chat_response())
    resp.raise_for_status = MagicMock()
    if status >= 400:
        exc = httpx.HTTPStatusError(
            message=f"HTTP {status}",
            request=MagicMock(),
            response=resp,
        )
        resp.raise_for_status.side_effect = exc
    return resp


def _default_chat_response(content: str = "Hello!") -> dict:
    return {
        "choices": [
            {
                "message": {"role": "assistant", "content": content, "tool_calls": None},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


def _make_messages() -> list[Message]:
    return [Message(role=Role.USER, content="Hi")]


# ---------------------------------------------------------------------------
# Test 1: ProviderRegistry.list_providers returns registered names
# ---------------------------------------------------------------------------


def test_list_providers_returns_registered_names():
    """list_providers() must include every registered provider."""
    names = ProviderRegistry.list_providers()
    assert "openrouter" in names
    assert "minimax" in names
    assert "ollama" in names
    assert "deepseek" in names


def test_provider_registry_recreates_instance_when_kwargs_change():
    """Provider instances are cached only while their configuration stays identical."""

    class RegistryTestProvider(BaseProvider):
        def __init__(self, api_key: str):
            self.api_key = api_key

        async def complete(self, messages, model, **kwargs):
            return ModelResponse(content="", model=model)

    ProviderRegistry._providers["registry_test"] = RegistryTestProvider
    ProviderRegistry._instances.pop("registry_test", None)
    ProviderRegistry._instance_keys.pop("registry_test", None)

    first = ProviderRegistry.get("registry_test", api_key="one")
    same = ProviderRegistry.get("registry_test", api_key="one")
    second = ProviderRegistry.get("registry_test", api_key="two")

    assert same is first
    assert second is not first
    assert second.api_key == "two"

    ProviderRegistry._providers.pop("registry_test", None)
    ProviderRegistry._instances.pop("registry_test", None)
    ProviderRegistry._instance_keys.pop("registry_test", None)


# ---------------------------------------------------------------------------
# Test 2: OpenRouterProvider.complete — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openrouter_complete_success():
    """OpenRouterProvider.complete returns a ModelResponse on 200."""
    resp = _fake_response(200, _default_chat_response("OpenRouter works"))

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=resp)
    mock_client.aclose = AsyncMock()

    with patch("cucumber_agent.providers.openrouter.httpx.AsyncClient", return_value=mock_client):
        provider = OpenRouterProvider(api_key="test-key")
        result = await provider.complete(_make_messages(), "openai/gpt-4o-mini")

    assert isinstance(result, ModelResponse)
    assert result.content == "OpenRouter works"
    assert result.input_tokens == 10
    assert result.output_tokens == 5


# ---------------------------------------------------------------------------
# Test 3: OpenRouterProvider.complete — retry on HTTP 429 then succeed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openrouter_retries_on_429():
    """OpenRouterProvider retries up to max_retries times on HTTP 429."""
    rate_limited = _fake_response(429)
    success = _fake_response(200, _default_chat_response("Retry OK"))

    mock_client = MagicMock()
    mock_client.post = AsyncMock(side_effect=[rate_limited, success])
    mock_client.aclose = AsyncMock()

    with patch("cucumber_agent.providers.openrouter.httpx.AsyncClient", return_value=mock_client):
        with patch("cucumber_agent.providers.openrouter.asyncio.sleep", new_callable=AsyncMock):
            provider = OpenRouterProvider(api_key="test-key")
            result = await provider.complete(_make_messages(), "openai/gpt-4o-mini", max_retries=3)

    assert result.content == "Retry OK"
    assert mock_client.post.call_count == 2


# ---------------------------------------------------------------------------
# Test 4: OllamaProvider.complete — retry on HTTP 503 then succeed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ollama_retries_on_503():
    """OllamaProvider retries on 503 Service Unavailable."""
    unavailable = _fake_response(503)
    success = _fake_response(200, _default_chat_response("Ollama OK"))

    mock_client = MagicMock()
    mock_client.post = AsyncMock(side_effect=[unavailable, success])
    mock_client.aclose = AsyncMock()

    with patch("cucumber_agent.providers.ollama.httpx.AsyncClient", return_value=mock_client):
        with patch("cucumber_agent.providers.ollama.asyncio.sleep", new_callable=AsyncMock):
            provider = OllamaProvider()
            result = await provider.complete(_make_messages(), "llama3.2", max_retries=3)

    assert result.content == "Ollama OK"
    assert mock_client.post.call_count == 2


# ---------------------------------------------------------------------------
# Test 5: DeepSeekProvider.complete — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deepseek_complete_success():
    """DeepSeekProvider.complete returns correct ModelResponse."""
    resp = _fake_response(200, _default_chat_response("DeepSeek answer"))

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=resp)
    mock_client.aclose = AsyncMock()

    with patch("cucumber_agent.providers.deepseek.httpx.AsyncClient", return_value=mock_client):
        provider = DeepSeekProvider(api_key="ds-key")
        result = await provider.complete(_make_messages(), "deepseek-chat")

    assert result.content == "DeepSeek answer"
    assert result.finish_reason == "stop"
    # Verify it hit the correct base URL
    call_args = mock_client.post.call_args
    assert "deepseek.com" in call_args[0][0]


# ---------------------------------------------------------------------------
# Test 6: DeepSeekProvider.complete — retry on HTTP 500 and ultimately fail
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deepseek_raises_after_max_retries():
    """DeepSeekProvider raises after exhausting all retries."""
    server_error = _fake_response(500)

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=server_error)
    mock_client.aclose = AsyncMock()

    with patch("cucumber_agent.providers.deepseek.httpx.AsyncClient", return_value=mock_client):
        with patch("cucumber_agent.providers.deepseek.asyncio.sleep", new_callable=AsyncMock):
            provider = DeepSeekProvider(api_key="ds-key")
            with pytest.raises(Exception):
                await provider.complete(_make_messages(), "deepseek-chat", max_retries=2)

    # Should have attempted max_retries times
    assert mock_client.post.call_count == 2


# ---------------------------------------------------------------------------
# Test 7: BaseProvider default stream falls back to complete()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_base_provider_default_stream_uses_complete():
    """The default stream() implementation yields complete()'s content."""

    class MinimalProvider(BaseProvider):
        async def complete(self, messages, model, **kwargs) -> ModelResponse:
            return ModelResponse(content="streamed via complete", model=model)

    provider = MinimalProvider()
    chunks = []
    async for chunk in provider.stream(_make_messages(), "test-model"):
        chunks.append(chunk)

    assert chunks == ["streamed via complete"]


# ---------------------------------------------------------------------------
# Test 8: OpenRouterProvider.close releases the HTTP client
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openrouter_close_calls_aclose():
    """close() must call aclose() on the underlying httpx client."""
    mock_client = MagicMock()
    mock_client.aclose = AsyncMock()

    with patch("cucumber_agent.providers.openrouter.httpx.AsyncClient", return_value=mock_client):
        provider = OpenRouterProvider(api_key="test-key")
        await provider.close()

    mock_client.aclose.assert_awaited_once()


# ---------------------------------------------------------------------------
# Test 9: OllamaProvider.complete — tool calls parsed correctly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ollama_parses_tool_calls():
    """OllamaProvider correctly parses tool_calls in the response."""
    tool_response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_abc",
                            "type": "function",
                            "function": {"name": "my_tool", "arguments": '{"x": 1}'},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3},
    }
    resp = _fake_response(200, tool_response)

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=resp)
    mock_client.aclose = AsyncMock()

    with patch("cucumber_agent.providers.ollama.httpx.AsyncClient", return_value=mock_client):
        provider = OllamaProvider()
        result = await provider.complete(_make_messages(), "llama3.2")

    assert result.tool_calls is not None
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "my_tool"
    assert result.tool_calls[0].arguments == {"x": 1}
    assert result.tool_calls[0].id == "call_abc"
