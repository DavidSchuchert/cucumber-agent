"""Provider system - pluggable LLM providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cucumber_agent.session import Message


class Role(Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass
class ToolCall:
    """A tool call requested by the model."""

    id: str
    name: str
    arguments: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ModelResponse:
    """Response from a model."""

    content: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    finish_reason: str | None = None
    tool_calls: list[ToolCall] | None = None


class BaseProvider(ABC):
    """Abstract base for all LLM providers."""

    @abstractmethod
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
        ...

    @abstractmethod
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
        ...


class ProviderRegistry:
    """Global registry for LLM providers."""

    _providers: dict[str, type[BaseProvider]] = {}
    _instances: dict[str, BaseProvider] = {}

    @classmethod
    def register(cls, name: str):
        """Decorator to register a provider class."""

        def inner(provider_cls: type[BaseProvider]) -> type[BaseProvider]:
            cls._providers[name] = provider_cls
            return provider_cls

        return inner

    @classmethod
    def get(cls, name: str, **kwargs) -> BaseProvider:
        """Get a provider instance by name."""
        if name not in cls._providers:
            available = ", ".join(cls._providers.keys()) or "none"
            raise ValueError(f"Unknown provider '{name}'. Available: {available}")
        if name not in cls._instances:
            cls._instances[name] = cls._providers[name](**kwargs)
        return cls._instances[name]

    @classmethod
    def list_providers(cls) -> list[str]:
        """List all registered provider names."""
        return list(cls._providers.keys())

    @classmethod
    def configure(cls, name: str, **kwargs) -> BaseProvider:
        """Configure and return a provider instance with given kwargs."""
        if name not in cls._providers:
            available = ", ".join(cls._providers.keys()) or "none"
            raise ValueError(f"Unknown provider '{name}'. Available: {available}")
        cls._instances[name] = cls._providers[name](**kwargs)
        return cls._instances[name]
