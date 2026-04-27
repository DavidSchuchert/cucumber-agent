# AGENTS.md

## Context

CucumberAgent is a clean, modular AI agent framework. We're building this from scratch to replace OpenClaw/Hermes which have become too complex and brittle.

## Session Startup

1. Load config from `~/.cucumber/config.yaml`
2. Create new Session
3. Start CLI REPL

## Memory

- Config lives in `~/.cucumber/config.yaml`
- Session history is in-memory for MVP
- Later: daily logs in `~/.cucumber/memory/`

## Tools (MVP Scope)

For MVP, we focus on:
- **Provider system** — pluggable LLM backends
- **Agent** — orchestrates provider + tools
- **CLI** — user-friendly REPL

## Adding a Provider

1. Create `src/cucumber_agent/providers/<name>.py`
2. Extend `BaseProvider`
3. Register with `@ProviderRegistry.register("<name>")`
4. Add to config.yaml defaults

## Adding a Skill (Future)

Skills are `/slash` commands. Each skill:
- Has a `skill.yaml` manifest
- Lives in `~/.cucumber/skills/`
- Is hot-reloadable

## Red Lines

- No destructive commands without asking
- No data exfiltration
- When in doubt, ask first
