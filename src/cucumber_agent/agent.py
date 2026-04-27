"""Agent - orchestrates providers, sessions, and tools."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from cucumber_agent.config import Config
from cucumber_agent.provider import BaseProvider, ProviderRegistry
from cucumber_agent.session import Message, Role, Session

# Import providers to trigger @ProviderRegistry.register decorators
from cucumber_agent.providers import minimax  # noqa: F401
from cucumber_agent.providers import openrouter  # noqa: F401

if TYPE_CHECKING:
    from cucumber_agent.config import AgentConfig


class Agent:
    """
    Core agent. Orchestrates provider calls and session management.
    Does NOT handle CLI or networking directly.
    """

    def __init__(
        self,
        provider: BaseProvider,
        config: AgentConfig,
    ):
        self._provider = provider
        self._config = config

    @classmethod
    def from_config(cls, config: Config | None = None) -> Agent:
        """Create an agent from configuration."""
        import os

        config = config or Config.load()
        provider_name = config.agent.provider
        provider_config = config.get_provider_config(provider_name)

        # Build kwargs from config
        kwargs: dict = {}
        if provider_config:
            if provider_config.api_key:
                kwargs["api_key"] = provider_config.api_key
            if provider_config.base_url:
                kwargs["base_url"] = provider_config.base_url
            if provider_config.model:
                kwargs["model"] = provider_config.model

        # Check env vars as fallback
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
        return cls(provider=provider, config=config.agent)

    async def run(self, session: Session, user_input: str) -> str:
        """
        Process user input and return the response text.
        Handles tool calls automatically.
        """
        # Add user message
        session.add_user_message(user_input)

        # Build messages for provider
        messages = self._build_messages(session)

        # Call provider
        response = await self._provider.complete(
            messages=messages,
            model=self._config.model,
            temperature=self._config.temperature,
            max_tokens=self._config.max_tokens,
        )

        # Add assistant response to session
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

        # Stream and yield chunks - stream() returns AsyncIterator (not coroutine)
        full_response = ""
        stream_iter = self._provider.stream(
            messages=messages,
            model=self._config.model,
            temperature=self._config.temperature,
            max_tokens=self._config.max_tokens,
        )
        async for chunk in stream_iter:
            full_response += chunk
            yield chunk

        # Store final response
        session.add_assistant_message(full_response)

    def _build_messages(self, session: Session) -> list[Message]:
        """Build the message list for the provider."""
        messages = []

        # Add system prompt
        if self._config.system_prompt:
            messages.append(
                Message(
                    role=Role.SYSTEM,
                    content=self._config.system_prompt,
                )
            )

        # Add conversation history
        messages.extend(session.messages)

        return messages
