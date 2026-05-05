# CucumberAgent Wiki

Willkommen in der CucumberAgent-Doku. Starte hier, wenn du wissen willst, wie
das Tool denkt, was es sich merkt und wie Herbert Swarm nachvollziehbar arbeitet.

## Quick Links

- [Architecture](Architecture.md) — Systemaufbau und Datenfluss
- [Memory & Personality](Memory.md) — Warum der Agent Persönlichkeit und Fakten nicht verliert
- [Providers](Providers.md) — Unterstützte KI-Provider
- [Configuration](Configuration.md) — Config-Dateien erklärt
- [CLI Commands](CLI.md) — Befehle und UX-Helfer
- [Skills](Skills.md) — Built-in und eigene Skills
- [AgentGuide](AgentGuide.md) — Agent-System-Guide
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

## Am Wichtigsten

1. `cucumber doctor` prüft Setup, Provider, Wiki, Skills und Workspace.
2. `/what-now` schlägt den nächsten sinnvollen Schritt vor.
3. `/remember key: value` speichert Fakten dauerhaft.
4. `/pin <text>` priorisiert Kontext für die aktuelle Session.
5. `/herbert-swarm <projekt>` plant Projektarbeit per KI, validiert den Plan und führt Tasks parallel aus.

## Features

- **Tool System** — shell, search, web_search, web_reader, agent, create_tool
- **Smart Retry** — Auto-retry READ commands on path errors (Bilder↔Pictures)
- **Thinking Blocks** — Display agent internal thoughts
- **Memory System** — Core identity, persistent facts, pinned context, summary, recent messages
- **Custom Tools** — Hot-reload from ~/.cucumber/custom_tools/
- **Skills** — YAML manifests in ~/.cucumber/skills/ + built-in herbert-swarm
- **/autopilot** — Native project-local task tracking (Sequential, not parallel)
- **/herbert-swarm** — Native multi-agent parallel project builder (Parallel, shared brain)
- **/doctor + /what-now** — Setup diagnosis and next-step guidance
- **/tips + /examples + /docs** — Built-in tips, copy-paste workflows, and wiki excerpts

## How It Works

1. **User runs `cucumber run`** → CLI starts.
2. **Config loaded from `~/.cucumber/`** → Provider, personality, user info.
3. **Memory loaded** → facts, pins, summaries and recent messages.
4. **System prompt built** → Core identity plus Memory & Identity Contract.
5. **Messages sent to Provider** → AI model plans, answers or asks for tools.
6. **Tool calls shown for approval** → User decides [1] Execute [2] Cancel [3] Edit.
7. **Response streamed back** → Thinking blocks displayed, Markdown rendered.

## For the Agent

If you need to fix something or understand the system:

- **Config loading**: `src/cucumber_agent/config.py` → `Config.load()`
- **Personality parsing**: `src/cucumber_agent/config.py` → `PersonalityConfig.from_markdown()`
- **Provider calls**: `src/cucumber_agent/agent.py` → `Agent.run_with_tools()`
- **Message trimming**: `src/cucumber_agent/agent.py` → `trim_messages()`
- **Smart retry**: `src/cucumber_agent/smart_retry.py` → command classification
- **Tool registry**: `src/cucumber_agent/tools/registry.py` → `ToolRegistry`
- **Skills loader**: `src/cucumber_agent/skills/loader.py` → `SkillLoader`
- **UX commands**: `src/cucumber_agent/cli.py` → `/doctor`, `/what-now`, `/tips`, `/examples`, `/docs`, `/explain-last`
