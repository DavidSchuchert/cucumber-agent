# CLI Commands

## `cucumber run`

Start an interactive chat session.

```bash
cucumber run
```

### What happens

1. Loads config from `~/.cucumber/config.yaml`
2. Loads personality from `~/.cucumber/personality/personality.md`
3. Restores previous session summary from disk (if memory is enabled)
4. Starts the REPL loop with tab-completion

## `cucumber init`

Run the interactive setup wizard again.

```bash
cucumber init
```

### What it asks

1. **Agent name** — What's the AI assistant's name?
2. **Language** — English or German (or other)
3. **Tone** — casual, friendly, professional, formal, or custom
4. **Greeting** — How should it greet users?
5. **Strengths** — What is it good at?
6. **Interests** — What topics does it care about?
7. **User info** — Your name, bio, GitHub, portfolio
8. **Preferences** — Web search, coding, memory
9. **Provider** — MiniMax, OpenRouter, DeepSeek, etc.
10. **API key** — Provider API key
11. **Model** — Which model to use
12. **Workspace** — Default working directory

### Output files

```
~/.cucumber/
├── config.yaml
├── personality/personality.md
└── user/user.md
```

## `cucumber config`

Show current configuration.

```bash
cucumber config
```

## `cucumber --help`

Show help.

```bash
cucumber --help
```

---

## REPL Commands

All commands start with `/`. Tab-completion is available for all of them.

### Conversation

| Command | Description |
|---------|-------------|
| `/help` | Show all available commands |
| `/exit` | Save session summary and exit |
| `/clear` | Clear conversation (workspace/facts metadata preserved) |
| `/history [N]` | Show last N messages (default 10) |
| `/undo` | Remove last user + assistant message pair |
| `/export` | Export session as Markdown to `~/Downloads/` |

### Multi-line Input

End any line with `\` to continue on the next line:

```
You> Write a Python function that\
  ... takes a list and\
  ... returns only even numbers
```

The prompt switches to `  ...` while accumulating. Send a line without `\` to submit.

### Context & Memory

| Command | Description |
|---------|-------------|
| `/context` | Show token usage, context %, live message count |
| `/compact` | Manually compress conversation history now |
| `/memory` | List all stored facts |
| `/remember key: value` | Store a persistent fact |
| `/forget key` | Delete a stored fact |
| `/pin <text>` | Pin text into the system prompt — survives compression |
| `/pin` | List all pinned items |
| `/unpin <nr>` | Remove a pinned item by number |

**How `/pin` works:** Pinned text is injected as high-priority context into every system prompt, above the operational instructions. It is never compressed or lost.

### Agent & Tools

| Command | Description |
|---------|-------------|
| `/tools` | List all registered tools and their auto-approve status |
| `/autoapprove` | Toggle session-wide tool auto-approve (incl. sub-agents) |
| `/skills` | List installed YAML skills |
| `/autopilot plan <goal>` | Create a safe project execution plan for the current workspace |
| `/autopilot run [--dry-run] [--parallel N] [--timeout SECONDS]` | Execute or simulate the current Autopilot plan |
| `/autopilot status` | Show Autopilot progress for this workspace |
| `/autopilot report` | Show task results, failures, and next steps |
| `/autopilot reset --yes` | Delete the local Autopilot state for this workspace |

Autopilot state is stored in `~/.cucumber/autopilot/` by workspace hash, so normal planning and status checks do not dirty the project repository.

**Tool Approval Dialog:**

When the agent wants to execute a tool that requires approval, a dialog appears:

```
[1] Ausführen    [2] Abbrechen    [3] Bearbeiten    [4] Alle akzeptieren
```

| Choice | Effect |
|--------|--------|
| `1` | Execute this tool call |
| `2` | Cancel this tool call |
| `3` | Edit the command before executing (shell tool only) |
| `4` | Auto-approve all remaining tool calls for this session (incl. sub-agents) |

**Sub-agent Tool Approval Dialog:**

```
[1] Ausführen    [2] Überspringen    [3] Bearbeiten    [4] Alle akzeptieren    [5] Abbrechen
```

| Choice | Effect |
|--------|--------|
| `1` | Execute this tool call |
| `2` | Skip this tool call |
| `3` | Edit command |
| `4` | Auto-approve all remaining calls for this sub-agent run |
| `5` | Abort the entire sub-agent |

### Stats & Info

| Command | Description |
|---------|-------------|
| `/config` | Show current provider/model/personality settings |
| `/model` | Show current provider and model |
| `/cost` | Show token counts and estimated USD cost for this session |
| `/debug` | Toggle debug mode (shows extra context info) |

### Personality

| Command | Description |
|---------|-------------|
| `/optimize` | Let the AI analyse its own name and suggest personality improvements (emoji, greeting, strengths) |

### Skills

| Command | Description |
|---------|-------------|
| `/skills` | List installed skills |
| `/<skillname> [args]` | Run a skill by its command name |

---

## Output Formatting

AI responses are formatted with [rich](https://github.com/Textualize/rich):

- **Code blocks** — Syntax highlighted (monokai theme), with language detection
- **Thinking blocks** — `<think>` / `<thinking>` blocks shown as dimmed italic text
- **Context bar** — Each response shows token count and context usage percentage
- **Panels** — Responses wrapped in a styled panel with the agent's emoji and name

---

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Normal exit |
| `1` | Error (no config, provider error, etc.) |

---

## Keyboard Shortcuts

| Shortcut | Effect |
|----------|--------|
| `Ctrl+C` | Cancel current operation / go back to prompt |
| `Ctrl+D` | Exit (saves session summary) |
| `Tab` | Command completion |
| `↑ / ↓` | Navigate input history |
