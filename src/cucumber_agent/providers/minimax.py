"""MiniMax provider - routes to MiniMax API."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

import httpx

from cucumber_agent.provider import BaseProvider, ModelResponse, ProviderRegistry, ToolCall
from cucumber_agent.session import Message

if TYPE_CHECKING:
    from cucumber_agent.session import ContentBlock


@ProviderRegistry.register("minimax")
class MiniMaxProvider(BaseProvider):
    """Provider for MiniMax API."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.minimax.io/anthropic",
        model: str = "MiniMax-M2.7",
    ):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01",
            },
            timeout=120.0,
        )

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    async def complete(
        self,
        messages: list[Message],
        model: str,
        *,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tools: list[dict] | None = None,
    ) -> ModelResponse:
        """Send a complete request and return the full response."""
        body = self._build_request(messages, model, temperature, max_tokens, tools)
        body["stream"] = False

        response = await self._client.post(
            f"{self._base_url}/v1/messages",
            json=body,
        )
        response.raise_for_status()
        data = response.json()

        return self._parse_response(data, model)

    def stream(
        self,
        messages: list[Message],
        model: str,
        *,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tools: list[dict] | None = None,
    ) -> AsyncIterator[str]:
        """Stream the response as an async iterator of text chunks."""

        async def generate():
            async with self._client.stream(
                "POST",
                f"{self._base_url}/v1/messages",
                json=self._build_request(messages, model, temperature, max_tokens, tools),
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        if data.get("type") == "content_block_delta":
                            delta = data.get("delta", {})
                            if content := delta.get("text"):
                                yield content
                    except json.JSONDecodeError:
                        continue

        async def runner():
            async for chunk in generate():
                yield chunk

        return runner()

    def _build_request(
        self,
        messages: list[Message],
        model: str,
        temperature: float,
        max_tokens: int | None,
        tools: list[dict] | None,
    ) -> dict:
        """Build the request body."""
        body = {
            "model": model,
            "messages": [self._format_message(m) for m in messages],
            "temperature": temperature,
            "stream": True,
        }
        if max_tokens:
            body["max_tokens"] = max_tokens
        if tools:
            body["tools"] = tools
        return body

    def _format_message(self, message: Message) -> dict:
        """Format a Message as a MiniMax message dict."""
        role = message.role.value
        content = self._extract_content(message.content)

        result: dict = {"role": role, "content": content}
        if message.name:
            result["name"] = message.name
        if message.tool_call_id:
            result["tool_call_id"] = message.tool_call_id

        return result

    def _extract_content(self, content: str | list[ContentBlock]) -> str:
        """Extract text content from a message."""
        if isinstance(content, str):
            return content
        parts = []
        for block in content:
            if block.type == "text" and block.text:
                parts.append(block.text)
            elif block.type == "tool_result" and block.content:
                parts.append(block.content)
        return "\n".join(parts) if parts else ""

    def _parse_response(self, data: dict, model: str) -> ModelResponse:
        """Parse a MiniMax response into a ModelResponse."""
        content = ""
        tool_calls: list[ToolCall] | None = None

        content_blocks = data.get("content", [])
        if isinstance(content_blocks, list):
            for block in content_blocks:
                if block.get("type") == "text":
                    content = block.get("text", "")
                elif block.get("type") == "tool_call":
                    # Parse tool call
                    tool_call_block = block.get("tool_call", {})
                    tool_calls = tool_calls or []
                    tool_calls.append(ToolCall(
                        id=tool_call_block.get("id", ""),
                        name=tool_call_block.get("name", ""),
                        arguments=tool_call_block.get("input", {}),
                    ))

        usage = data.get("usage", {})
        return ModelResponse(
            content=content,
            model=model,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            finish_reason=data.get("stop_reason"),
            tool_calls=tool_calls,
        )
