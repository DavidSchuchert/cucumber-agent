"""Ollama provider — local LLM via the OpenAI-compatible API."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

import httpx

from cucumber_agent.provider import BaseProvider, ModelResponse, ProviderRegistry, ToolCall
from cucumber_agent.session import Message

if TYPE_CHECKING:
    from cucumber_agent.session import ContentBlock


@ProviderRegistry.register("ollama")
class OllamaProvider(BaseProvider):
    """Provider for locally running Ollama models."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434/v1",
        model: str = "llama3.2",
        api_key: str = "ollama",  # Ollama doesn't use this but httpx requires a value
    ):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=120.0,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def complete(
        self,
        messages: list[Message],
        model: str,
        *,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tools: list[dict] | None = None,
        system_override: str | None = None,
    ) -> ModelResponse:
        """Non-streaming completion."""
        body = self._build_request(
            messages, model, temperature, max_tokens, tools,
            system_override=system_override, stream=False,
        )
        response = await self._client.post(
            f"{self._base_url}/chat/completions",
            json=body,
        )
        response.raise_for_status()
        return self._parse_response(response.json(), model)

    async def stream(
        self,
        messages: list[Message],
        model: str,
        *,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tools: list[dict] | None = None,
    ) -> AsyncIterator[str]:
        """Streaming completion."""
        body = self._build_request(messages, model, temperature, max_tokens, tools, stream=True)
        async with self._client.stream("POST", f"{self._base_url}/chat/completions", json=body) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                data = json.loads(data_str)
                choices = data.get("choices", [])
                if choices:
                    delta = choices[0].get("delta", {})
                    if content := delta.get("content"):
                        yield content

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
