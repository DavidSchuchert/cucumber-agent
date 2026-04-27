# 🥒 CucumberAgent

![CucumberAgent Logo](assets/logo.png)

> A clean, modular AI agent framework. Built from scratch.

```bash
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

### One-Line Install

```bash
curl -LsSf https://get.cucumber.sh/install.sh | sh
```

### Setup Wizard

```bash
cucumber init
```

The wizard asks for:
- Agent name (e.g., "Cucumber", "Herbert")
- Language (English, German, or custom)
- Communication tone (casual, friendly, professional, formal)
- Greeting, strengths, interests
- Provider selection (MiniMax, OpenRouter, DeepSeek, etc.)
- API key and model

### Run

```bash
cucumber run
```

## Directory Structure

```
~/.cucumber/
├── config.yaml              # Provider, API key, preferences
├── personality/
│   └── personality.md       # Agent name, tone, language, greeting
├── user/
│   └── user.md              # Your info (name, bio, github)
└── memory/                  # (future) Conversation memory
```

## Architecture

```
cucumber-agent/
├── src/cucumber_agent/
│   ├── __main__.py          # Entry point
│   ├── provider.py          # BaseProvider + Registry
│   ├── session.py           # Session + Message
│   ├── agent.py             # Agent orchestration
│   ├── config.py            # YAML + Markdown config
│   ├── cli.py               # REPL
│   └── providers/           # LLM backends
├── installer/
│   ├── install.sh           # One-line installer
│   └── init.py              # Setup wizard
├── wiki/                    # Full documentation
└── pyproject.toml
```

## Providers

- [x] MiniMax (fast, cheap)
- [x] OpenRouter (many models)
- [ ] DeepSeek
- [ ] NVIDIA NIM
- [ ] LM Studio (local)

## Features

- [x] Streaming responses
- [x] Token budget management (context trimming)
- [x] Personality system (name, tone, language)
- [x] Multi-provider support
- [x] Clean structured config (YAML + Markdown)
- [ ] Skill system (`/slash` commands)
- [ ] Plugin system (MCP integration)
- [ ] Memory system

## Documentation

Full docs in [wiki/](wiki/):
- [Architecture](wiki/Architecture.md) — How the system works
- [Configuration](wiki/Configuration.md) — Config files explained
- [Providers](wiki/Providers.md) — Adding new providers
- [CLI](wiki/CLI.md) — Command reference

## Development

```bash
git clone https://github.com/DavidSchuchert/cucumber-agent.git
cd cucumber-agent
uv sync

# Format + type check
uv run ruff format
uv run ruff check

# Test
uv run pytest

# Run locally
uv run cucumber run
```