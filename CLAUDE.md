# CLAUDE.md

# Current Date
Today's date is 2026-04-27.

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
├── provider.py       # BaseProvider ABC + ProviderRegistry
├── session.py        # Session + Message types
├── agent.py          # Agent.run()
├── config.py         # ~/.cucumber/config.yaml
├── cli.py            # REPL interface
├── __main__.py      # cucumber run
└── providers/       # Provider implementations
```

## Provider Interface

```python
class BaseProvider(ABC):
    @abstractmethod
    async def complete(self, messages: list[Message], model: str) -> ModelResponse: ...

    @abstractmethod
    async def stream(self, messages: list[Message], model: str) -> AsyncIterator[str]: ...
```

## Registry Pattern

Providers register via decorator:

```python
@ProviderRegistry.register("openrouter")
class OpenRouterProvider(BaseProvider):
    ...
```

## CLI Commands

```bash
cucumber run       # Start REPL
cucumber init     # Setup wizard
cucumber config   # Show config
```

## Verification

Before committing: `uv run ruff format && uv run ruff check && uv run ty check && uv run pytest`
