# Architecture

## Overview

CucumberAgent is built with a simple, modular architecture:

```
┌─────────────────────────────────────────────────────────┐
│                        CLI                               │
│                   (src/cucumber_agent/cli.py)            │
│                                                              │
│  REPL Loop: read → Agent → stream → display                │
│  Tool approval: [1] Execute [2] Cancel [3] Edit            │
│  Thinking blocks displayed in subtle gray                    │
└─────────────────────┬─────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│                       Agent                              │
│                 (src/cucumber_agent/agent.py)            │
│                                                              │
│  - Orchestrates providers and sessions                     │
│  - Trims messages to fit token budget                      │
│  - Builds system prompt from personality                   │
│  - synthesize() for tool result responses                  │
│  - 3-tier memory: pinned → summary → recent               │
└─────────────────────┬─────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│                     Provider                            │
│              (src/cucumber_agent/provider.py)            │
│                                                              │
│  BaseProvider ABC + ProviderRegistry                        │
│  - complete() → full response                              │
│  - stream() → chunked response                            │
└─────────────────────┬─────────────────────────────────────┘
                      │
        ┌─────────────┼─────────────┐
        ▼             ▼             ▼
   ┌─────────┐   ┌───────────┐   ┌─────────┐
   │ MiniMax │   │ OpenRouter│   │  Ollama │
   └─────────┘   └───────────┘   └─────────┘
```

## Key Files

### `src/cucumber_agent/`

| File | Purpose |
|------|---------|
| `__main__.py` | Entry point: `cucumber run` |
| `cli.py` | REPL loop, tool approval flow, thinking display |
| `agent.py` | Core logic, message building, synthesize() |
| `config.py` | YAML + Markdown config loading |
| `session.py` | Message, Session dataclasses |
| `provider.py` | BaseProvider ABC, ProviderRegistry |
| `memory.py` | SessionLogger + FactsStore |
| `smart_retry.py` | Command classification, auto-retry logic |
| `workspace.py` | Project type detection (Python, Node, Rust, etc.) |
| `providers/` | Provider implementations (minimax, openrouter, ollama) |
| `tools/` | Built-in tools + custom tool loader |
| `skills/` | YAML skill system with hot-reload |

### Config Locations

```
~/.cucumber/
├── config.yaml              # Provider, API key, preferences
├── personality/
│   └── personality.md       # Name, tone, language, greeting
├── user/
│   └── user.md              # User info
├── memory/                  # Session logs + facts
├── custom_tools/            # Hot-reload custom Python tools
└── skills/                  # YAML skill manifests
```

## Data Flow

```
1. User input → cli.py
2. cli.py → agent.run_with_tools()
3. agent.py → builds messages with system prompt from personality.md
4. agent.py → trims messages if > max_tokens
5. agent.py → provider.complete() with tools spec
6. provider → HTTP request to AI API
7. Response → tool calls shown for approval
8. User approves → tool executed → synthesize() → display
9. Session → stores conversation history
10. memory.py → logs sessions to daily markdown files
```

## Tool System

```
┌─────────────────────────────────────────┐
│              ToolRegistry               │
│    (src/cucumber_agent/tools/registry.py)│
├─────────────────────────────────────────┤
│  Built-in Tools:                        │
│  - shell: command execution             │
│  - search: file/directory search        │
│  - web_search: DuckDuckGo               │
│  - web_reader: URL content extraction    │
│  - agent: recursive sub-agent           │
│  - create_tool: self-generating tools    │
├─────────────────────────────────────────┤
│  Custom Tools:                           │
│  ~/.cucumber/custom_tools/*.py           │
│  (hot-reload on mtime change)            │
└─────────────────────────────────────────┘
```

## Smart Retry Flow

```
Command fails with "not found" error
    │
    ▼
smart_retry.py: classify_command()
    │
    ├── READ (ls, cat, find) ──→ Auto-retry ✓
    ├── WRITE (echo, mkdir) ────→ User approval
    └── DESTRUCTIVE (rm, mv) ───→ Never auto-retry ✗
    │
    ▼
Path mapping: Bilder ↔ Pictures (German ↔ English)
    │
    ▼
Max 2 retries, then explain to user
```

## Memory Architecture

```
3-Tier Memory:
┌──────────────────────────────────────┐
│ Tier 1: Pinned (System)              │
│ - personality.md                      │
│ - ~/.cucumber/memory/facts.md         │
└──────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────┐
│ Tier 2: Summary (Session)            │
│ - ~/.cucumber/memory/2026-04-28.md   │
│ - Daily session logs                 │
└──────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────┐
│ Tier 3: Recent (Context)             │
│ - Last N messages in session         │
│ - Trimmed to fit token budget         │
└──────────────────────────────────────┘
```

## Token Budget

Context trimming happens in `agent.py`:

```
max_tokens (default 8000)
├── system_prompt tokens
├── buffer (200 tokens)
└── conversation history
```

If history exceeds budget, oldest messages are trimmed first.