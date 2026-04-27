"""Agent - orchestrates providers, sessions, and tools."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from cucumber_agent.config import Config
from cucumber_agent.provider import BaseProvider, ProviderRegistry
from cucumber_agent.providers import (
    minimax,  # noqa: F401
    openrouter,  # noqa: F401
)
from cucumber_agent.session import Message, Role, Session

if TYPE_CHECKING:
    pass


def estimate_tokens(text: str) -> int:
    """Rough estimate of tokens (1 token ≈ 4 chars)."""
    return len(text) // 4


def trim_messages(
    messages: list[Message],
    max_tokens: int,
    system_prompt_tokens: int,
) -> list[Message]:
    """Trim messages to fit within token budget."""
    budget = max_tokens - system_prompt_tokens - 200  # buffer

    if budget <= 0:
        return []

    current_tokens = sum(estimate_tokens(str(m.content)) for m in messages)
    if current_tokens <= budget:
        return messages

    # Keep messages fitting in budget, oldest first
    trimmed: list[Message] = []
    for msg in reversed(messages):
        msg_tokens = estimate_tokens(str(msg.content))
        if current_tokens + msg_tokens <= budget:
            trimmed.insert(0, msg)
            current_tokens += msg_tokens
        else:
            break

    return trimmed


# Greeting patterns for detecting first contact
GREETING_PATTERNS = [
    r"^hi\b", r"^hello\b", r"^hey\b", r"^yo\b", r"^sup\b",
    r"^moin\b", r"^servus\b", r"^hallo\b",
    r"^guten\s*morgen\b", r"^guten\s*tag\b", r"^grüß?e?\b",
]


def is_greeting(text: str) -> bool:
    """Check if text is a greeting."""
    text_lower = text.lower().strip()
    return any(re.match(p, text_lower) for p in GREETING_PATTERNS)


class Agent:
    """Core agent. Orchestrates provider calls and session management."""

    def __init__(self, provider: BaseProvider, config: Config):
        self._provider = provider
        self._config = config
        self._context_config = config.context
        self._agent_config = config.agent
        self._optimization_offered = False

    @classmethod
    def from_config(cls, config: Config | None = None) -> Agent:
        """Create an agent from configuration."""
        import os

        config = config or Config.load()
        provider_name = config.agent.provider
        provider_config = config.get_provider_config(provider_name)

        kwargs: dict = {}
        if provider_config:
            if provider_config.api_key:
                kwargs["api_key"] = provider_config.api_key
            if provider_config.base_url:
                kwargs["base_url"] = provider_config.base_url
            if provider_config.model:
                kwargs["model"] = provider_config.model

        env_key_map = {
            "openrouter": "OPENROUTER_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "nvidia_nim": "NVIDIA_NIM_API_KEY",
        }
        if provider_config and provider_config.api_key is None:
            env_var = env_key_map.get(provider_name)
            if env_var and env_var in os.environ:
                kwargs["api_key"] = os.environ[env_var]

        provider = ProviderRegistry.get(provider_name, **kwargs)
        return cls(provider=provider, config=config)

    def needs_optimization(self, user_input: str) -> bool:
        """Check if greeting and optimization hasn't been offered yet."""
        return not self._optimization_offered and is_greeting(user_input)

    def mark_optimization_offered(self) -> None:
        """Mark that optimization has been offered."""
        self._optimization_offered = True

    @property
    def personality(self):
        """Access personality config."""
        return self._config.personality

    def get_tools_spec(self) -> list[dict] | None:
        """Get tool specifications for the current provider."""
        # Tools disabled for now - need proper approval flow first
        return None
        # from cucumber_agent.tools import ToolRegistry
        # provider = self._config.agent.provider
        # return ToolRegistry.get_tools_spec(provider)

    async def run(self, session: Session, user_input: str) -> str:
        """Process user input and return the response text."""
        session.add_user_message(user_input)
        messages = self._build_messages(session)
        tools = self.get_tools_spec()

        response = await self._provider.complete(
            messages=messages,
            model=self._agent_config.model,
            temperature=self._agent_config.temperature,
            max_tokens=self._agent_config.max_tokens,
            tools=tools if tools else None,
        )

        session.add_assistant_message(response.content)
        return response.content

    async def run_stream(
        self,
        session: Session,
        user_input: str,
    ) -> AsyncIterator[str]:
        """Stream the response as chunks."""
        session.add_user_message(user_input)
        messages = self._build_messages(session)
        tools = self.get_tools_spec()

        # If tools are enabled, use complete() to get full response
        if tools:
            response = await self._provider.complete(
                messages=messages,
                model=self._agent_config.model,
                temperature=self._agent_config.temperature,
                max_tokens=self._agent_config.max_tokens,
                tools=tools,
            )
            yield response.content
            session.add_assistant_message(response.content)
            return

        # No tools - use streaming
        full_response = ""
        stream_iter = self._provider.stream(
            messages=messages,
            model=self._agent_config.model,
            temperature=self._agent_config.temperature,
            max_tokens=self._agent_config.max_tokens,
        )
        async for chunk in stream_iter:
            full_response += chunk
            yield chunk

        session.add_assistant_message(full_response)

    def _build_messages(self, session: Session) -> list[Message]:
        """Build message list with context trimming."""
        messages = []

        system_prompt = self._agent_config.system_prompt
        if system_prompt:
            messages.append(Message(role=Role.SYSTEM, content=system_prompt))

        system_tokens = estimate_tokens(system_prompt)
        max_tokens = self._context_config.max_tokens

        history = session.messages

        remember_last = self._context_config.remember_last
        if remember_last > 0 and len(history) > remember_last:
            history = history[-remember_last:]

        if history:
            trimmed = trim_messages(history, max_tokens, system_tokens)
            messages.extend(trimmed)

        return messages
