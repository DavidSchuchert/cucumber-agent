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
    """Provider for MiniMax API using OpenAI compatibility layer."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.minimax.io/v1",
        model: str = "MiniMax-M2.7",
    ):
        self._api_key = api_key
        # Strip trailing slash and remove /anthropic if the user config still has it
        url = base_url.rstrip("/")
        if url.endswith("/anthropic"):
            url = url[:-10] + "/v1"
        self._base_url = url
        self._model = model
        self._client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
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
        body = self._build_request(
            messages, model, temperature, max_tokens, tools,
            system_override=system_override, stream=False,
        )

        import asyncio

        for attempt in range(max_retries):
            try:
                response = await self._client.post(
                    f"{self._base_url}/chat/completions",
                    json=body,
                )

                # Handle 529 with retry
                if response.status_code == 529:
                    wait_time = 2 ** attempt
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

        raise Exception("Max retries exceeded")

    async def stream(
        self,
        messages: list[Message],
        model: str,
        *,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tools: list[dict] | None = None,
    ) -> AsyncIterator[str]:
        """Stream the response as an async iterator of text chunks."""
        body = self._build_request(messages, model, temperature, max_tokens, tools, stream=True)
        async with self._client.stream("POST", f"{self._base_url}/chat/completions", json=body) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                    choices = data.get("choices", [])
                    if choices:
                        delta = choices[0].get("delta", {})
                        if content := delta.get("content"):
                            yield content
                except json.JSONDecodeError:
                    continue

    def _build_request(
        self,
        messages: list[Message],
        model: str,
        temperature: float,
        max_tokens: int | None,
        tools: list[dict] | None,
        *,
        system_override: str | None = None,
        stream: bool = False,
    ) -> dict:
        """Build the request body."""
        formatted = []
        for m in messages:
            if system_override and m.role.value == "system":
                formatted.append({"role": "system", "content": system_override})
            else:
                formatted.append(self._format_message(m))

        body: dict = {
            "model": model,
            "messages": formatted,
            "temperature": temperature,
            "stream": stream,
        }
        if max_tokens:
            body["max_tokens"] = max_tokens
        if tools:
            body["tools"] = tools
        return body

    def _format_message(self, message: Message) -> dict:
        role = message.role.value
        content = self._extract_content(message.content)
        result: dict = {"role": role, "content": content}
        if message.name:
            result["name"] = message.name
        if message.tool_call_id:
            result["tool_call_id"] = message.tool_call_id
        if message.tool_calls:
            result["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                }
                for tc in message.tool_calls
            ]
        return result

    def _extract_content(self, content: str | list[ContentBlock]) -> str:
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
        choices = data.get("choices", [{}])
        choice = choices[0] if choices else {}
        message = choice.get("message", {})
        content = message.get("content", "") or ""

        tool_calls_data = message.get("tool_calls", [])
        tool_calls: list[ToolCall] | None = None
        if tool_calls_data:
            tool_calls = []
            for tc in tool_calls_data:
                func = tc.get("function", {})
                tool_calls.append(ToolCall(
                    id=tc.get("id", ""),
                    name=func.get("name", ""),
                    arguments=json.loads(func.get("arguments", "{}")),
                ))

        usage = data.get("usage", {})
        return ModelResponse(
            content=content,
            model=model,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            finish_reason=choice.get("finish_reason"),
            tool_calls=tool_calls,
        )
