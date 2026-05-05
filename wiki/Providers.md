# Providers

CucumberAgent supports multiple AI providers via a pluggable provider system.

Built-in providers:

| Provider | Config name | Notes |
|----------|-------------|-------|
| MiniMax | `minimax` | Default hosted provider |
| OpenRouter | `openrouter` | OpenAI-compatible multi-model routing |
| DeepSeek | `deepseek` | Direct DeepSeek API |
| Ollama | `ollama` | Local OpenAI-compatible Ollama endpoint |

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
5. If it should appear in `cucumber init`, add it to `installer/init.py`

## Example

```python
from collections.abc import AsyncIterator

from cucumber_agent.provider import BaseProvider, ModelResponse, ProviderRegistry, ToolCall
from cucumber_agent.session import Message, Role


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
        tools: list[dict] | None = None,
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

    async def close(self) -> None:
        # Cleanup if needed
        ...
```

## ModelResponse

Already defined in `provider.py`:

```python
@dataclass
class ModelResponse:
    content: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    finish_reason: str | None = None
    tool_calls: list[ToolCall] | None = None

@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict
```

## Supported Providers

### MiniMax

- **Name**: `minimax`
- **API URL**: `https://api.minimax.io/anthropic`
- **Models**: MiniMax-M2.7
- **Speed**: Fast, 204k context
- **Cost**: Cheap
- **Features**: Thinking blocks, tool use, 529 retry logic

### MiniMax MCP Tools

CucumberAgent unterstützt MiniMax MCP-Tools:

#### web_search
- Sucht im Internet nach aktuellen Informationen
- Nutzt MiniMax API wenn `MINIMAX_API_KEY` gesetzt ist
- Fallback auf DuckDuckGo wenn kein API Key

#### understand_image
- Analysiert Bilder und beschreibt deren Inhalt
- Unterstützt HTTP/HTTPS URLs und lokale Dateien
- Formate: JPEG, PNG, GIF, WebP (max 20MB)

### OpenRouter

- **Name**: `openrouter`
- **API URL**: `https://openrouter.ai/api/v1`
- **Models**: openai/gpt-4o-mini, openai/gpt-4o, anthropic/claude-3.5-sonnet, etc.
- **Speed**: Varies by model
- **Cost**: Varies

### Ollama

- **Name**: `ollama`
- **API URL**: `http://localhost:11434/v1`
- **Models**: llama3.2, mistral, codellama, etc.
- **Speed**: Depends on local hardware
- **Cost**: Free (local)
- **Setup**: `ollama serve` must be running

## Message Format

Messages are converted to provider format internally:

```python
@dataclass
class Message:
    role: Role  # SYSTEM, USER, ASSISTANT, TOOL
    content: str | list[ContentBlock]
    name: str | None = None
    tool_call_id: str | None = None
```

Providers receive `list[Message]` and handle their own serialization.
