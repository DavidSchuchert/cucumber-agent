# Providers

CucumberAgent supports multiple AI providers via a pluggable provider system.

## Architecture

```
BaseProvider (ABC)
    ├── complete() → full response
    └── stream() → async iterator of chunks

ProviderRegistry
    ├── register(name) → decorator
    └── get(name) → provider instance
```

## Adding a New Provider

1. Create `src/cucumber_agent/providers/<name>.py`
2. Implement `BaseProvider` subclass
3. Decorate with `@ProviderRegistry.register("<name>")`
4. Import in `providers/__init__.py`

## Example

```python
from collections.abc import AsyncIterator
from dataclasses import dataclass

from cucumber_agent.provider import BaseProvider, ModelResponse, ProviderRegistry, Role
from cucumber_agent.session import Message


@dataclass
class ModelResponse:
    content: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    finish_reason: str | None = None


@ProviderRegistry.register("myprovider")
class MyProvider(BaseProvider):
    def __init__(self, api_key: str, base_url: str | None = None):
        self.api_key = api_key
        self.base_url = base_url or "https://api.myprovider.com/v1"

    async def complete(
        self,
        messages: list[Message],
        model: str,
        *,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        # Make HTTP request, return ModelResponse
        ...

    def stream(
        self,
        messages: list[Message],
        model: str,
        *,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        # Yield text chunks
        ...
```

## Supported Providers

### MiniMax

- **Name**: `minimax`
- **API URL**: `https://api.minimax.io/anthropic`
- **Models**: MiniMax-M2.7
- **Speed**: Fast, 204k context
- **Cost**: Cheap

### OpenRouter

- **Name**: `openrouter`
- **API URL**: `https://openrouter.ai/api/v1`
- **Models**: openai/gpt-4o-mini, openai/gpt-4o, anthropic/claude-3.5-sonnet, etc.
- **Speed**: Varies by model
- **Cost**: Varies

## Message Format

Messages are converted to provider format internally:

```python
@dataclass
class Message:
    role: Role  # SYSTEM, USER, ASSISTANT, TOOL
    content: str | list[ContentBlock]
```

Providers receive `list[Message]` and handle their own serialization.
