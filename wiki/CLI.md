# CLI Commands

## `cucumber run`

Start an interactive chat session.

```bash
cucumber run
```

### What happens

1. Loads config from `~/.cucumber/config.yaml`
2. Loads personality from `~/.cucumber/personality/personality.md`
3. Creates a new Session
4. Starts a REPL loop
5. Streams AI responses in real-time

### Usage

```bash
# Normal startup
cucumber run

# With debug output
DEBUG=1 cucumber run
```

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

After setup, these files are created:

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

## REPL Commands

Inside the interactive session:

| Command | Description |
|---------|-------------|
| `exit` or `quit` | End session |
| `Ctrl+C` | Cancel current response |
| `Ctrl+D` | Exit |

## Exit Codes

- `0` — Normal exit
- `1` — Error (no config, provider error, etc.)