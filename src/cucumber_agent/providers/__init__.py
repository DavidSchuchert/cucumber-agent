"""Provider system - pluggable LLM providers."""

from cucumber_agent.provider import BaseProvider, ProviderRegistry, ModelResponse

# Import all providers to register them with the registry
# This triggers the @ProviderRegistry.register decorators
from cucumber_agent.providers.minimax import MiniMaxProvider
from cucumber_agent.providers.openrouter import OpenRouterProvider

__all__ = ["BaseProvider", "ProviderRegistry", "ModelResponse"]
