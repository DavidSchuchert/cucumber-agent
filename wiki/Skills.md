# Skills

Skills are YAML manifests in `~/.cucumber/skills/` that provide `/slash` commands for common tasks. They are **hot-reloaded** when files change.

## Built-in Skills (via `swarm` Tool)

Two powerful orchestration skills are built into the `swarm` tool itself:

### Herbert Swarm (`/herbert-swarm`)

**Native multi-agent project builder.** Analyzes a SPEC.md, creates phased tasks, runs real parallel sub-agents.

```bash
/herbert-swarm init --project ~/Documents/MeinProjekt
/herbert-swarm plan --project ~/Documents/MeinProjekt
/herbert-swarm run --project ~/Documents/MeinProjekt --parallel 5
```

See [Swarm.md](Swarm.md) for full documentation.

### Autopilot (`/autopilot`)

**Sequential task tracking.** Helps one agent break down and track a complex task into steps.

```bash
/autopilot start Mein großes Feature
/autopilot plan Noch ein Step
/autopilot status
```

See [Autopilot.md](Autopilot.md) for full documentation.

## User-Defined Skills (YAML)

Skills in `~/.cucumber/skills/*.yaml` are loaded as `/slash` commands.

### Available Skills

| Skill | Command | Description |
|-------|---------|-------------|
| **calendar** | `/calendar` | Create Apple Calendar events |
| **clipboard** | `/clipboard` | Read/write clipboard |
| **email** | `/email` | Send email via Apple Mail |
| **notes** | `/notes` | Create/view Apple Notes |
| **open** | `/open` | Open URL or search in browser |
| **reminder** | `/reminder` | Create Apple Reminders |
| **screenshot** | `/screenshot` | Take screenshots (full/area/window) |
| **sysinfo** | `/sysinfo` | Show system information |
| **timer** | `/timer` | Set countdown timer |
| **wetter** | `/wetter` | Weather forecast |
| **wifi** | `/wifi` | WiFi status and networks |
| **imessage** | `/imessage` | Send iMessage/SMS via Apple Messages |

## Skill Format

```yaml
name: skill_name
command: /command
description: What this skill does
args_hint: "[hint for args]"
prompt: |
  Instructions for the agent when this skill is called.
  Use {args} placeholder for user input.
```

## Adding Custom Skills

Create a `.yaml` file in `~/.cucumber/skills/`:

```yaml
name: my_skill
command: /myskill
description: Does something cool
args_hint: "[required arg]"
prompt: |
  When this skill is invoked, the agent will:
  1. Parse {args}
  2. Use tools to accomplish the task
  3. Confirm the result to the user
```

## Commands

```
/skills     List all available skills
```

Skills are visible to the AI in the `/skills` command output.
