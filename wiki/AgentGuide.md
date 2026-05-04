# Agent Guide (for the Agent)

This guide helps you understand the CucumberAgent system so you can fix issues or extend functionality.

## System Overview

You are CucumberAgent. Your personality lives in `~/.cucumber/personality/personality.md`. Your configuration (provider, model) is in `~/.cucumber/config.yaml`.

## Built-in Tools

| Tool | What it does |
|------|-------------|
| `shell` | Execute shell commands (with approval system) |
| `search` | Search files by name or content |
| `web_search` | DuckDuckGo search |
| `web_reader` | Extract content from URLs |
| `agent` | Spawn a sub-agent for complex tasks |
| `create_tool` | Generate new custom tools |
| `swarm` | **Multi-agent project builder** (see below) |

## Swarm Tool — Multi-Agent Project Builder

The `swarm` tool is **built-in and native** to CucumberAgent. It is NOT an external tool.

### Quick Start
```
/herbert-swarm init --project ~/Documents/MeinProjekt
/herbert-swarm plan --project ~/Documents/MeinProjekt
/herbert-swarm run --project ~/Documents/MeinProjekt --parallel 5
```

### Commands
- `init` — Create swarm brain for a project
- `plan` — Analyze SPEC.md and create task plan
- `run` — Execute all tasks with parallel sub-agents
- `status` — Show task progress
- `report` — Show results and created files
- `brain` — Show internal brain state
- `reset` — Clear brain (reset everything)

### How it Works

1. **`init`** creates `~/.swarm_brain.json` (or `<project>/.swarm_brain.json`)
2. **`plan`** reads SPEC.md, keyword-scans it, creates phased tasks
3. **`run`** spawns real async sub-agents — one per task — that execute in parallel
4. Each sub-agent uses `shell`, `write_file`, `read_file`, `search` etc.
5. Sub-agents auto-approve tools (user explicitly started the swarm)

### Brain Structure

```json
{
  "project_name": "MeinProjekt",
  "tasks": {
    "task-001": {
      "id": "task-001",
      "description": "Create API endpoints",
      "agent_role": "coder",
      "files": ["backend/api/routes.py"],
      "dependencies": [],
      "status": "done",
      "phase": 3
    }
  },
  "facts": {
    "task_001_result": {
      "files_created": ["/abs/path/to/file.py"],
      "summary": "Created FastAPI endpoints"
    }
  },
  "phases": ["INFRA", "BACKEND_CORE", "BACKEND_API", "FRONTEND", "TESTING"],
  "current_phase": 3
}
```

### Phase Detection (Keyword-Based)

The planner scans SPEC.md content for these keywords:

| Stack | Keywords detected |
|-------|------------------|
| Backend | fastapi, flask, django, express, python, api, rest, graphql |
| Frontend | react, vue, svelte, next.js, vite, tailwind, typescript |
| Database | postgresql, mongodb, redis, sqlite, sqlalchemy, prisma |
| Docker | docker, compose, kubernetes |
| CI/Testing | pytest, jest, github actions, coverage |

### IMPORTANT: Planner Limitations

**The planner does NOT detect:**
- Vanilla JavaScript / HTML-only projects
- PHP projects
- Static sites without package.json/vite.config

For these projects: **manually write tasks into the brain JSON** instead of relying on `plan`.

### As a Sub-Agent in Swarm

When you run as a swarm sub-agent:
1. You get a prompt with `TASK: <description>` and `Files to create/modify: <list>`
2. Implement ALL files completely — no TODOs, no placeholders
3. After completion, update the brain:
   ```
   shell: cat <brain_file>
   → Read current brain JSON
   → Add to brain["facts"]["task_<id>_result"]:
     {"files_created": [<abs_paths>], "summary": "<one sentence>"}
   → shell: write_file(<brain_file>, <updated_json>)
   ```
4. On error: update `brain["tasks"]["<id>"]["status"] = "failed"` and set error message

## Autopilot — Sequential Task Tracking

**Autopilot** is NOT swarm — it tracks ONE agent's sequential task progress.

### Commands
- `/autopilot start [goal]` — Create a new plan
- `/autopilot plan [task title]` — Add tasks to plan
- `/autopilot status` — Show all tasks
- `/autopilot next` — Show next pending task
- `/autopilot done [id]` — Mark task done
- `/autopilot fail [id] [reason]` — Mark task failed
- `/autopilot report` — Summary

### State File
`~/.cucumber/autopilot/<workspace_hash>/autopilot_state.json`

### Swarm vs Autopilot

| | Swarm | Autopilot |
|---|---|---|
| Tasks | Parallel (real sub-agents) | Sequential (one agent) |
| Plan source | SPEC.md auto-analysis | Manual by agent |
| Brain | Yes (shared) | No (local state) |
| Best for | Full-stack projects | Feature implementation |

## Common Issues & Fixes

### Config not loading
1. Check if `~/.cucumber/config.yaml` exists
2. If not, user needs to run `cucumber init`
3. Config code: `src/cucumber_agent/config.py` → `Config.load()`

### Provider errors
1. Check API key (config.yaml or environment)
2. Verify provider name matches exactly
3. Provider code: `src/cucumber_agent/providers/<name>.py`

### Token limit exceeded
1. Check `context.max_tokens` in config.yaml (default 8000)
2. Check `context.remember_last` (default 10)
3. Trimming code: `src/cucumber_agent/agent.py` → `trim_messages()`

### Smart Retry Not Working
Smart retry is in `src/cucumber_agent/smart_retry.py`. Check:
1. `preferences.smart_retry` in config.yaml is true
2. Command classified as READ (ls, cat, find, etc.)
3. Error contains "not found"

Path mappings: Bilder↔Pictures, Dokumente↔Documents

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

## Key Code Locations

| What | Where |
|------|-------|
| Entry point | `src/cucumber_agent/__main__.py` |
| REPL loop | `src/cucumber_agent/cli.py` |
| Agent logic | `src/cucumber_agent/agent.py` |
| **Swarm tool** | `src/cucumber_agent/tools/swarm.py` |
| **Autopilot** | `src/cucumber_agent/autopilot.py` |
| Config loading | `src/cucumber_agent/config.py` |
| Session/Message | `src/cucumber_agent/session.py` |
| Provider system | `src/cucumber_agent/provider.py` |
| MiniMax provider | `src/cucumber_agent/providers/minimax.py` |
| Tool registry | `src/cucumber_agent/tools/registry.py` |
| Smart retry | `src/cucumber_agent/smart_retry.py` |
| Memory system | `src/cucumber_agent/memory.py` |
| Skills loader | `src/cucumber_agent/skills/loader.py` |

## Debugging Tips

1. **Use /debug** — Type `/debug` in the REPL to see session state
2. **Check config** — `cucumber config`
3. **View personality** — `cat ~/.cucumber/personality/personality.md`
4. **Test config loading** — `uv run python -c "from cucumber_agent.config import Config; c = Config.load(); print(c.agent.provider)"`
5. **Test swarm directly** — `cd ~/.cucumber-agent && uv run python -m cucumber_agent run` then try `/herbert-swarm ...`
