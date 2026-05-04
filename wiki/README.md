# CucumberAgent Wiki

Welcome to the CucumberAgent documentation!

## Quick Links

- [Architecture](Architecture.md) — How the system is built
- [Providers](Providers.md) — Supported AI providers
- [Configuration](Configuration.md) — Config files explained
- [CLI Commands](CLI.md) — Command reference
- [Skills](Skills.md) — Built-in and custom skills
- [AgentGuide](AgentGuide.md) — Agent system guide
- **[Swarm](Swarm.md)** — Multi-Agent Project Builder (Herbert Swarm)
- **[Autopilot](Autopilot.md)** — Sequential Task Tracking

## Directory Structure

```
~/.cucumber/
├── config.yaml              # Main config (provider, API key, preferences)
├── personality/
│   └── personality.md       # Agent name, tone, language, greeting, etc.
├── user/
│   └── user.md              # User info (name, bio, github, portfolio)
├── memory/                  # Session logs + persistent facts
├── custom_tools/            # Hot-reload custom Python tools
└── skills/                  # YAML skill manifests
```

## Features

- **Tool System** — shell, search, web_search, web_reader, agent, create_tool
- **Smart Retry** — Auto-retry READ commands on path errors (Bilder↔Pictures)
- **Thinking Blocks** — Display agent internal thoughts
- **Memory System** — 3-tier: pinned → session → recent
- **Custom Tools** — Hot-reload from ~/.cucumber/custom_tools/
- **Skills** — YAML manifests in ~/.cucumber/skills/ + built-in herbert-swarm
- **/autopilot** — Native project-local task tracking (Sequential, not parallel)
- **/herbert-swarm** — Native multi-agent parallel project builder (Parallel, shared brain)

## How It Works

1. **User runs `cucumber run`** → CLI starts
2. **Config loaded from `~/.cucumber/`** → Provider, personality, user info
3. **System prompt built** → Includes personality, skills, tool instructions
4. **Messages sent to Provider** → AI model processes with tools
5. **Tool calls shown for approval** → User decides [1] Execute [2] Cancel [3] Edit
6. **Response streamed back** → Thinking blocks displayed, markdown rendered

## For the Agent

If you need to fix something or understand the system:

- **Config loading**: `src/cucumber_agent/config.py` → `Config.load()`
- **Personality parsing**: `src/cucumber_agent/config.py` → `PersonalityConfig.from_markdown()`
- **Provider calls**: `src/cucumber_agent/agent.py` → `Agent.run_with_tools()`
- **Message trimming**: `src/cucumber_agent/agent.py` → `trim_messages()`
- **Smart retry**: `src/cucumber_agent/smart_retry.py` → command classification
- **Tool registry**: `src/cucumber_agent/tools/registry.py` → `ToolRegistry`
- **Skills loader**: `src/cucumber_agent/skills/loader.py` → `SkillLoader`
