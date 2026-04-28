# CLAUDE.md

# Current Date
Today's date is 2026-04-28.

## Project

**CucumberAgent** — 🥒 A clean, modular AI agent framework built from scratch.

## Coding Environment

- **Python 3.14** — use `uv run` instead of global `python`
- Install `uv` if not present: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- All files go in `src/cucumber_agent/`
- Format: `uv run ruff format` + `uv run ruff check` + `uv run ty check`
- Tests: `uv run pytest`

## Architecture

```
src/cucumber_agent/
├── __main__.py          # Entry: cucumber run
├── cli.py              # REPL loop, tool approval flow
├── agent.py            # Core Agent with synthesize(), memory
├── config.py           # ~/.cucumber/config.yaml
├── session.py          # Session + Message types
├── memory.py           # SessionLogger + FactsStore
├── provider.py         # BaseProvider ABC + ProviderRegistry
├── smart_retry.py      # Command classification + auto-retry
├── workspace.py         # Project type detection
├── providers/          # Provider implementations
│   ├── minimax.py
│   ├── openrouter.py
│   └── ollama.py
├── tools/              # Tool system
│   ├── base.py         # BaseTool + ToolResult
│   ├── registry.py     # ToolRegistry
│   ├── loader.py       # Hot-reload custom tools
│   ├── shell.py        # Command execution
│   ├── search.py       # File search
│   ├── web_search.py   # DuckDuckGo
│   ├── web_reader.py   # URL content extraction
│   ├── agent.py        # Sub-agent tool
│   └── create_tool.py  # Self-generating tools
└── skills/             # YAML skill system
    ├── loader.py
    └── runner.py
```

## Provider Interface

```python
class BaseProvider(ABC):
    @abstractmethod
    async def complete(self, messages, model, *, tools=None) -> ModelResponse: ...

    @abstractmethod
    def stream(self, messages, model, *, tools=None) -> AsyncIterator[str]: ...

    async def close(self) -> None: ...
```

## Registry Pattern

Providers register via decorator:

```python
@ProviderRegistry.register("openrouter")
class OpenRouterProvider(BaseProvider):
    ...
```

## Tool System

Tools are registered with BaseTool:

```python
class MyTool(BaseTool):
    name = "my_tool"
    description = "Does something"
    parameters = {
        "type": "object",
        "properties": {...},
        "required": [...]
    }

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, output="...")
```

Custom tools go in `~/.cucumber/custom_tools/*.py` and hot-reload on mtime change.

## Smart Retry

`smart_retry.py` classifies commands:

- `READ` — ls, cat, find, etc. → safe to auto-retry on "not found"
- `WRITE` — echo, touch, mkdir → needs approval
- `DESTRUCTIVE` — rm, mv → never auto-retry

Path mapping: Bilder↔Pictures, Dokumente↔Documents (German↔English)

## CLI Commands

```bash
cucumber run        # Start REPL
cucumber init      # Setup wizard
cucumber config     # Show config
cucumber update     # Update from GitHub
```

REPL Commands (type in chat):
- `/help` — Show help
- `/exit` — Quit
- `/clear` — Clear session
- `/config` — Show config
- `/model` — Show model
- `/debug` — Toggle debug mode
- `/optimize` — Optimize personality
- `/skills` — List skills
- `/memory` — Show memory
- `/remember` — Store fact
- `/forget` — Remove fact

## Verification

Before committing: `uv run ruff format && uv run ruff check && uv run ty check && uv run pytest`
