# CucumberAgent Wiki

Welcome to the CucumberAgent documentation!

## Quick Links

- [Architecture](Architecture.md) — How the system is built
- [Providers](Providers.md) — Supported AI providers
- [Configuration](Configuration.md) — Config files explained
- [CLI Commands](CLI.md) — Command reference

## Directory Structure

```
~/.cucumber/
├── config.yaml              # Main config (provider, API key, preferences)
├── personality/
│   └── personality.md       # Agent name, tone, language, greeting, etc.
├── user/
│   └── user.md              # User info (name, bio, github, portfolio)
├── memory/                  # (future) Conversation memory
└── logs/                    # (future) Session logs
```

## How It Works

1. **User runs `cucumber run`** → CLI starts
2. **Config loaded from `~/.cucumber/`** → Provider, personality, user info
3. **Personality.md → System Prompt** → Agent knows who it is
4. **Messages sent to Provider** → AI model processes
5. **Response streamed back** → User sees it in real-time

## For the Agent

If you need to fix something or understand the system:

- **Config loading**: `src/cucumber_agent/config.py` → `Config.load()`
- **Personality parsing**: `src/cucumber_agent/config.py` → `PersonalityConfig.from_markdown()`
- **Provider calls**: `src/cucumber_agent/agent.py` → `Agent.run()`
- **Message trimming**: `src/cucumber_agent/agent.py` → `trim_messages()` — limits context to save tokens
