"""Provider system - pluggable LLM providers."""

from cucumber_agent.provider import BaseProvider, ModelResponse, ProviderRegistry

# Import all providers to register them with the registry
# This triggers the @ProviderRegistry.register decorators
from cucumber_agent.providers import (
    minimax,  # noqa: F401
    openrouter,  # noqa: F401
)

__all__ = [
    "BaseProvider",
    "ProviderRegistry",
    "ModelResponse",
    "minimax",
    "openrouter",
]
