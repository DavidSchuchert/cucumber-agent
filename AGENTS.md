# AGENTS.md

## Context

CucumberAgent is a clean, modular AI agent framework built from scratch.

## Session Startup

1. Load config from `~/.cucumber/config.yaml`
2. Load personality from `~/.cucumber/personality/personality.md`
3. Create new Session
4. Start CLI REPL with thinking block display

## Memory System

- **Tier 1 (Pinned):** personality.md + facts.md
- **Tier 2 (Session):** Daily logs in ~/.cucumber/memory/
- **Tier 3 (Recent):** In-memory, trimmed to fit token budget

## Tool System

Built-in tools:
- **shell** — Command execution with user approval
- **search** — File/directory search
- **web_search** — DuckDuckGo instant answers
- **web_reader** — URL content extraction
- **agent** — Recursive sub-agent
- **create_tool** — Self-generating custom tools

Custom tools: `~/.cucumber/custom_tools/*.py` (hot-reload)

## Smart Retry

Commands are classified:
- **READ** (ls, cat, find): Auto-retry on "not found"
- **WRITE** (echo, mkdir): Needs approval on retry
- **DESTRUCTIVE** (rm, mv): Never auto-retry

Path mapping for macOS: Bilder↔Pictures, Dokumente↔Documents

## Adding a Provider

1. Create `src/cucumber_agent/providers/<name>.py`
2. Extend `BaseProvider`
3. Register with `@ProviderRegistry.register("<name>")`
4. Add to config.yaml defaults

## Adding a Skill

Skills are YAML manifests in `~/.cucumber/skills/*.yaml`:

```yaml
name: code_review
description: Review code for bugs
prompt: "Review this code: {args}"
```

## Red Lines

- No destructive commands without asking
- No data exfiltration
- When in doubt, ask first
- Max 2 auto-retries before giving up
