"""MiniMax provider - routes to MiniMax API."""

from __future__ import annotations

import asyncio
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
        max_retries: int = 3,
        system_override: str | None = None,
    ) -> ModelResponse:
        """Send a complete request and return the full response."""
        body = self._build_request(messages, model, temperature, max_tokens, tools, system_override)
        body["stream"] = False

        for attempt in range(max_retries):
            try:
                response = await self._client.post(
                    f"{self._base_url}/v1/messages",
                    json=body,
                )

                # Handle 529 with retry
                if response.status_code == 529:
                    wait_time = 2 ** attempt  # 1, 2, 4 seconds
                    if attempt < max_retries - 1:
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        response.raise_for_status()

                response.raise_for_status()
                data = response.json()
                return self._parse_response(data, model)

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 529 and attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    await asyncio.sleep(wait_time)
                    continue
                raise

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
        system_override: str | None = None,
    ) -> dict:
        """Build the request body."""
        formatted_messages = [self._format_message(m) for m in messages]

        # Override system message if specified
        if system_override:
            for msg in formatted_messages:
                if msg.get("role") == "system":
                    msg["content"] = system_override
                    break

        body = {
            "model": model,
            "messages": formatted_messages,
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

        if role == "tool":
            return {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": message.tool_call_id,
                        "content": self._extract_content(message.content)
                    }
                ]
            }

        content_blocks = []
        if message.content:
            content_blocks.append({"type": "text", "text": self._extract_content(message.content)})
            
        if message.tool_calls:
            for tc in message.tool_calls:
                content_blocks.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": tc.arguments
                })

        return {
            "role": role,
            "content": content_blocks if (content_blocks and role != "system") else self._extract_content(message.content)
        }

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
                elif block.get("type") == "thinking":
                    # Skip thinking blocks - not part of final response
                    continue
                elif block.get("type") in ("tool_call", "tool_use"):
                    # Parse tool call (MiniMax uses "tool_use" or "tool_call")
                    tool_calls = tool_calls or []
                    tool_calls.append(ToolCall(
                        id=block.get("id", ""),
                        name=block.get("name", ""),
                        arguments=block.get("input", {}),
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
