# Skills

Skills are YAML manifests in `~/.cucumber/skills/` that provide `/slash` commands for common tasks.

## Built-in Skills

Skills are automatically loaded from `~/.cucumber/skills/*.yaml` and hot-reloaded when files change.

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

## Example Skills

### Reminder
```
/reminder Milch kaufen
```
→ Creates an Apple Reminder with AppleScript

### Weather
```
/wetter Berlin
```
→ Searches DuckDuckGo for weather info

### Screenshot
```
/screenshot full
/screenshot area
/screenshot window
```
→ Saves to ~/Desktop/

### System Info
```
/sysinfo
/sysinfo battery
/sysinfo disk
```
→ Shows system statistics

## Commands

```
/skills     List all available skills
```

Skills are visible to the AI in the `/skills` command output.
