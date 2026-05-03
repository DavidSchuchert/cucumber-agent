# 🥒 CucumberAgent

> A clean, modular AI agent framework. Built from scratch.

```bash
curl -LsSf https://raw.githubusercontent.com/DavidSchuchert/cucumber-agent/main/installer/install.sh | sh
cucumber init
cucumber run
```

## Why

OpenClaw and Hermes are great but have grown into complex, brittle systems. CucumberAgent is:

- **Minimal** — Core only, features added as needed
- **Clean** — Simple ABCs, no magic
- **User-friendly** — `curl | sh` install, interactive setup wizard
- **Extensible** — Provider, Skill, and Tool systems

## Quick Start

### One-Line Install

```bash
curl -LsSf https://raw.githubusercontent.com/DavidSchuchert/cucumber-agent/main/installer/install.sh | sh
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
- Provider selection (MiniMax, OpenRouter, Ollama, etc.)
- API key and model

### Update

Stay up to date with the latest features and fixes:

```bash
curl -LsSf https://raw.githubusercontent.com/DavidSchuchert/cucumber-agent/main/installer/update.sh | sh
```

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
├── memory/                  # Session logs + persistent facts
├── custom_tools/            # Hot-reload custom Python tools
└── skills/                  # YAML skill manifests
```

## Architecture

```
cucumber-agent/
├── src/cucumber_agent/
│   ├── __main__.py          # Entry point
│   ├── provider.py          # BaseProvider ABC + Registry
│   ├── session.py           # Session + Message types
│   ├── agent.py             # Agent orchestration
│   ├── config.py            # YAML + Markdown config
│   ├── cli.py               # REPL interface
│   ├── memory.py            # SessionLogger + FactsStore
│   ├── workspace.py          # Project type detection
│   ├── smart_retry.py       # Auto-retry logic
│   ├── providers/            # LLM backend implementations
│   ├── tools/               # Built-in + custom tools
│   └── skills/              # YAML skill system
├── installer/
│   ├── install.sh           # One-line installer
│   └── init.py              # Setup wizard
├── wiki/                    # Full documentation
└── pyproject.toml
```

## Features

- [x] Streaming responses
- [x] Token budget management (context trimming)
- [x] **3-tier memory architecture** — immutable personality anchor, operational context, compressed history
- [x] Personality system (name, tone, language) — survives context compression
- [x] Multi-provider support (MiniMax, OpenRouter, Ollama, DeepSeek)
- [x] Clean structured config (YAML + Markdown)
- [x] **Tool system** — shell, search, web search, web reader, agent, calculator
- [x] **Custom tools** — hot-reload from `~/.cucumber/custom_tools/`
- [x] **Skill system** — YAML manifests with `{args}` expansion
- [x] **Memory system** — session logging (markdown + SQLite) + persistent facts store
- [x] **Smart retry** — auto-retry READ commands on path errors
- [x] **Thinking blocks** — display agent internal thoughts
- [x] **Workspace detection** — auto-detect Python, Node, Rust, etc.
- [x] **Sub-agent tool** — recursive delegation, 15-step loop, auto-approve propagation
- [x] **Context management** — `/compact`, `/context`, `/pin`, `/unpin`
- [x] **Token cost tracking** — `/cost` shows per-session usage and estimated USD
- [x] **Multi-line input** — end any line with `\` to continue on the next line
- [x] **Auto-approve** — `[4]` or `/autoapprove` silences all tool prompts (incl. sub-agents)

## Tools

CucumberAgent comes with built-in tools:

| Tool | Description |
|------|-------------|
| `shell` | Execute commands with user approval, auto-retry on path errors |
| `search` | Find files/directories by name |
| `web_search` | DuckDuckGo instant answers (no API key) |
| `web_reader` | Extract content from URLs |
| `agent` | Recursive sub-agent (max 15 steps) |
| `create_tool` | Self-generating custom tools |

Add custom tools to `~/.cucumber/custom_tools/*.py`

## Skills

Skills are YAML manifests in `~/.cucumber/skills/`:

```yaml
name: code_review
description: Review code for bugs
prompt: "Review this code: {args}\n\nFocus on: security, bugs, performance"
```

Use with `/code_review <file>`

## Documentation

Full docs in [wiki/](wiki/):
- [Architecture](wiki/Architecture.md) — How the system works
- [Configuration](wiki/Configuration.md) — Config files explained
- [Providers](wiki/Providers.md) — Adding new providers
- [CLI](wiki/CLI.md) — Command reference
- [AgentGuide](wiki/AgentGuide.md) — Agent system guide
- [Skills](wiki/Skills.md) — Built-in and custom skills

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

## Providers

- [x] MiniMax (fast, cheap)
- [x] OpenRouter (many models)
- [x] Ollama (local models)
- [ ] DeepSeek
- [ ] NVIDIA NIM