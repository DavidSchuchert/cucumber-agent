"""MiniMax provider - routes to MiniMax API."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

import httpx
from rich.console import Console

from cucumber_agent.provider import BaseProvider, ModelResponse, ProviderRegistry, ToolCall
from cucumber_agent.session import Message

console = Console()

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
            timeout=300.0,
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
            messages,
            model,
            temperature,
            max_tokens,
            tools,
            system_override=system_override,
            stream=False,
        )

        for attempt in range(max_retries):
            try:
                response = await self._client.post(
                    f"{self._base_url}/chat/completions",
                    json=body,
                )

                # Handle 529 or 429 with retry
                if response.status_code in (429, 529):
                    wait_time = 2**attempt
                    if attempt < max_retries - 1:
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        response.raise_for_status()

                response.raise_for_status()
                text = response.text.strip()
                if not text:
                    console.print("[yellow]MiniMax returned empty response[/yellow]")
                    raise ValueError("Empty response from MiniMax API")
                try:
                    data = json.loads(text)
                except json.JSONDecodeError as e:
                    console.print(f"[red]MiniMax JSON Parse Error:[/red] {e}")
                    console.print(f"[red]Response text:[/red] {text[:500]}")
                    raise ValueError(f"Invalid JSON from MiniMax: {e}") from e
                return self._parse_response(data, model)

            except (httpx.HTTPStatusError, httpx.TimeoutException) as e:
                # Determine if we should retry (only for transient errors)
                is_transient = isinstance(e, httpx.TimeoutException)
                if isinstance(e, httpx.HTTPStatusError):
                    is_transient = (
                        e.response.status_code in (429, 529) or e.response.status_code >= 500
                    )

                if is_transient and attempt < max_retries - 1:
                    wait_time = 2**attempt
                    if isinstance(e, httpx.TimeoutException):
                        console.print(
                            f"[yellow]MiniMax Timeout (Versuch {attempt + 1}/{max_retries}): {e}[/yellow]"
                        )
                    else:
                        console.print(
                            f"[yellow]MiniMax API Fehler {e.response.status_code} (Versuch {attempt + 1}/{max_retries})[/yellow]"
                        )
                    await asyncio.sleep(wait_time)
                    continue

                if isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 400:
                    console.print(f"[red]MiniMax API Error (400):[/red] {e.response.text}")
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
        max_retries: int = 3,
    ) -> AsyncIterator[str]:
        """Stream the response as an async iterator of text chunks."""
        body = self._build_request(messages, model, temperature, max_tokens, tools, stream=True)
        for attempt in range(max_retries):
            try:
                async with self._client.stream(
                    "POST", f"{self._base_url}/chat/completions", json=body
                ) as resp:
                    if resp.status_code in (429, 529) and attempt < max_retries - 1:
                        await asyncio.sleep(2**attempt)
                        continue
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            return
                        try:
                            data = json.loads(data_str)
                            choices = data.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                if content := delta.get("content"):
                                    yield content
                        except json.JSONDecodeError:
                            continue
                    return  # success — exit retry loop
            except (httpx.HTTPStatusError, httpx.TimeoutException) as e:
                # Determine if we should retry (only for transient errors)
                is_transient = isinstance(e, httpx.TimeoutException)
                if isinstance(e, httpx.HTTPStatusError):
                    is_transient = (
                        e.response.status_code in (429, 529) or e.response.status_code >= 500
                    )

                if not is_transient or attempt >= max_retries - 1:
                    raise

                wait_time = 2**attempt
                if isinstance(e, httpx.TimeoutException):
                    console.print(
                        f"[yellow]MiniMax Stream Timeout (Versuch {attempt + 1}/{max_retries})[/yellow]"
                    )
                else:
                    console.print(
                        f"[yellow]MiniMax Stream API Fehler {e.response.status_code} (Versuch {attempt + 1}/{max_retries})[/yellow]"
                    )
                await asyncio.sleep(wait_time)

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
        result: dict = {"role": role, "content": content or ""}

        # In OpenAI format, 'name' is only for 'user' or 'system' (rarely)
        # and 'tool_call_id' is for 'tool' role.
        # Strict providers like MiniMax might reject 'name' in 'tool' messages.
        if message.name and role != "tool":
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

        # Strip thinking blocks from content
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
        content = re.sub(
            r"<thinking>.*?</thinking>", "", content, flags=re.DOTALL | re.IGNORECASE
        ).strip()

        tool_calls_data = message.get("tool_calls", [])
        tool_calls: list[ToolCall] | None = None
        if tool_calls_data:
            tool_calls = []
            for tc in tool_calls_data:
                func = tc.get("function", {})
                tool_calls.append(
                    ToolCall(
                        id=tc.get("id", ""),
                        name=func.get("name", ""),
                        arguments=json.loads(func.get("arguments", "{}")),
                    )
                )

        usage = data.get("usage", {})
        return ModelResponse(
            content=content,
            model=model,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            finish_reason=choice.get("finish_reason"),
            tool_calls=tool_calls,
        )
