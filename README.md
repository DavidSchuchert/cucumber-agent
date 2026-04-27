# 🥒 CucumberAgent

> A clean, modular AI agent framework. Built from scratch.

```
curl -LsSf https://get.cucumber.sh/install.sh | sh
cucumber init
cucumber run
```

## Why

OpenClaw and Hermes are great but have grown into complex, brittle systems. CucumberAgent is:

- **Minimal** — Core only, features added as needed
- **Clean** — Simple ABCs, no magic
- **User-friendly** — `curl | sh` install, interactive setup wizard
- **Extensible** — Provider, Skill, and Plugin systems

## Quick Start

```bash
# Install
curl -LsSf https://get.cucumber.sh/install.sh | sh

# Setup (interactive wizard)
cucumber init

# Run
cucumber run
```

## Architecture

```
cucumber-agent/
├── src/cucumber_agent/
│   ├── provider.py       # BaseProvider + Registry
│   ├── session.py        # Session + Message
│   ├── agent.py          # Agent orchestration
│   ├── config.py         # YAML config
│   ├── cli.py            # REPL
│   └── providers/        # LLM backends
├── installer/
└── pyproject.toml
```

## Providers

- [ ] NVIDIA NIM
- [ ] OpenRouter
- [ ] DeepSeek
- [ ] LM Studio (local)

## Roadmap

- [x] Project structure
- [ ] Provider system
- [ ] Agent + Session
- [ ] CLI REPL
- [ ] Config system
- [ ] Installation wizard
- [ ] First provider (OpenRouter)

## Development

```bash
git clone https://github.com/cucumber/cucumber-agent.git
cd cucumber-agent
uv sync

# Format + type check
uv run ruff format
uv run ruff check
uv run ty check

# Test
uv run pytest
```
