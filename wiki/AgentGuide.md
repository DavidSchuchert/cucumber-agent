# Agent Guide (for the Agent)

This guide helps you understand the CucumberAgent system so you can fix issues or extend functionality.

## System Overview

You are CucumberAgent. Your personality and identity live in `~/.cucumber/personality/personality.md`. Your configuration (provider, model, preferences) is in `~/.cucumber/config.yaml`.

## Common Issues & Fixes

### Config not loading

1. Check if `~/.cucumber/config.yaml` exists
2. If not, user needs to run `cucumber init`
3. Config loading code: `src/cucumber_agent/config.py` → `Config.load()`

### Provider errors

1. Check if API key is set (in config.yaml or environment)
2. Verify provider name matches (e.g., "minimax", "openrouter")
3. Provider code: `src/cucumber_agent/providers/<name>.py`

### Token limit exceeded

1. Check `context.max_tokens` in config.yaml (default 8000)
2. Check `context.remember_last` (default 10)
3. Trimming code: `src/cucumber_agent/agent.py` → `trim_messages()`

### Wrong personality/language

Personality is loaded from `~/.cucumber/personality/personality.md`. Edit that file to change:
- `name` — your name
- `emoji` — your avatar emoji
- `tone` — communication style
- `language` — response language
- `greeting`, `strengths`, `interests`

### Smart Retry Not Working

Smart retry is in `src/cucumber_agent/smart_retry.py`. Check:
1. `preferences.smart_retry` in config.yaml is true
2. Command is classified as READ (ls, cat, find, etc.)
3. Error message contains "not found" or similar

Path mappings: Bilder↔Pictures, Dokumente↔Documents

### Memory System Issues

Memory is in `src/cucumber_agent/memory.py`:
- `SessionLogger` logs exchanges to ~/.cucumber/memory/
- `FactsStore` persists key/value facts to ~/.cucumber/memory/facts.md
- `/memory` and `/remember` commands in CLI

### Custom Tools Not Loading

Custom tools go in `~/.cucumber/custom_tools/*.py`. They must:
1. Extend `BaseTool` from `cucumber_agent.tools.base`
2. Implement `execute()` method
3. Return `ToolResult(success=True/False, output=..., error=...)`

### Skills Not Available

Skills are YAML files in `~/.cucumber/skills/*.yaml`. Format:
```yaml
name: my_skill
command: /myskill
description: What it does
prompt: "Instructions with {args} placeholder"
```

### Self-Optimization

On first greeting, the agent offers to optimize its own personality. The AI analyzes its name and suggests better emoji/greeting/strengths. This is handled by:
- `cli.py` → `_handle_optimization_response()` - manages the offer flow
- `cli.py` → `parse_personality_update()` - parses `PERSONALITY_UPDATE:...` from AI
- `cli.py` → `apply_personality_update()` - applies changes to personality.md

## Key Code Locations

| What | Where |
|------|-------|
| Entry point | `src/cucumber_agent/__main__.py` |
| REPL loop | `src/cucumber_agent/cli.py` |
| Agent logic | `src/cucumber_agent/agent.py` |
| Config loading | `src/cucumber_agent/config.py` |
| Session/Message | `src/cucumber_agent/session.py` |
| Provider system | `src/cucumber_agent/provider.py` |
| MiniMax provider | `src/cucumber_agent/providers/minimax.py` |
| OpenRouter provider | `src/cucumber_agent/providers/openrouter.py` |
| Ollama provider | `src/cucumber_agent/providers/ollama.py` |
| Tool registry | `src/cucumber_agent/tools/registry.py` |
| Smart retry | `src/cucumber_agent/smart_retry.py` |
| Memory system | `src/cucumber_agent/memory.py` |
| Skills loader | `src/cucumber_agent/skills/loader.py` |
| Custom tools | `src/cucumber_agent/tools/loader.py` |
| Workspace | `src/cucumber_agent/workspace.py` |

## Debugging Tips

1. **Use /debug**: Type `/debug` in the REPL to see session state
2. **Check config**: `cucumber config`
3. **View personality file**: `cat ~/.cucumber/personality/personality.md`
4. **Test config loading**: `uv run python -c "from cucumber_agent.config import Config; c = Config.load(); print(c.agent.provider)"`

## File Format Notes

### personality.md

```markdown
# Personality
name: Cucumber
tone: friendly
language: en
greeting: Hi! I'm Cucumber...
strengths: coding, research
interests: AI, Python
```

### config.yaml

YAML format. Key sections:
- `agent.provider` — "minimax", "openrouter", etc.
- `agent.model` — model identifier
- `context.max_tokens` — token budget for context
- `context.remember_last` — how many messages to keep

## Provider API Keys

If API key issues, check:
1. `~/.cucumber/config.yaml` → `providers.<name>.api_key`
2. Environment variables: `MINIMAX_API_KEY`, `OPENROUTER_API_KEY`, etc.
