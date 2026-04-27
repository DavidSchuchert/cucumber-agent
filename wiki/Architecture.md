# Architecture

## Overview

CucumberAgent is built with a simple, modular architecture:

```
┌─────────────────────────────────────────────────────────┐
│                        CLI                               │
│                   (src/cucumber_agent/cli.py)            │
│                                                              │
│  REPL Loop: read → Agent → stream → display                │
└─────────────────────┬─────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│                       Agent                              │
│                 (src/cucumber_agent/agent.py)            │
│                                                              │
│  - Orchestrates providers and sessions                    │
│  - Trims messages to fit token budget                     │
│  - Builds system prompt from personality                  │
└─────────────────────┬─────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│                     Provider                            │
│              (src/cucumber_agent/provider.py)            │
│                                                              │
│  BaseProvider ABC + ProviderRegistry                       │
│  - complete() → full response                             │
│  - stream() → chunked response                           │
└─────────────────────┬─────────────────────────────────────┘
                      │
        ┌─────────────┼─────────────┐
        ▼             ▼             ▼
   ┌─────────┐   ┌───────────┐   ┌─────────┐
   │ MiniMax │   │ OpenRouter│   │  ...   │
   └─────────┘   └───────────┘   └─────────┘
```

## Key Files

### `src/cucumber_agent/`

| File | Purpose |
|------|---------|
| `__main__.py` | Entry point: `cucumber run` |
| `cli.py` | REPL loop, user interaction |
| `agent.py` | Core logic, message building, token trimming |
| `config.py` | YAML + Markdown config loading |
| `session.py` | Message, Session dataclasses |
| `provider.py` | BaseProvider ABC, ProviderRegistry |
| `providers/` | Provider implementations (minimax, openrouter) |

### Config Locations

```
~/.cucumber/
├── config.yaml              # Provider, API key, preferences
├── personality/
│   └── personality.md       # Name, tone, language, greeting
├── user/
│   └── user.md              # User info
└── memory/                  # (future)
```

## Data Flow

```
1. User input → cli.py
2. cli.py → agent.run_stream()
3. agent.py → builds messages with system prompt from personality.md
4. agent.py → trims messages if > max_tokens
5. agent.py → provider.complete() or provider.stream()
6. provider → HTTP request to AI API
7. Response → streamed back to cli.py
8. cli.py → displayed to user
9. Session → stores conversation history
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
