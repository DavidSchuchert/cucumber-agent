# Configuration

CucumberAgent uses a structured directory layout under `~/.cucumber/`:

```
~/.cucumber/
├── config.yaml              # Main config
├── personality/
│   └── personality.md       # Agent personality
├── user/
│   └── user.md              # User information
└── memory/                  # Facts, logs, session summaries
```

## config.yaml

The main configuration file. Auto-generated during `cucumber init`.

```yaml
agent:
  provider: minimax
  model: MiniMax-M2.7
  temperature: 0.7
  max_tokens: null
  system_prompt: >-
    I ALWAYS communicate in English. ALL my responses must be in English.
    My name is Cucumber...

providers:
  minimax:
    api_key: your-api-key-here
    base_url: https://api.minimax.io/v1
    model: MiniMax-M2.7

preferences:
  can_search_web: true
  can_code: true
  can_remember: true
  smart_retry: true       # Auto-retry READ commands on path errors

context:
  max_tokens: 8000        # Max tokens for context window
  remember_last: 10       # Keep last N messages

memory:
  enabled: true
  log_dir: ~/.cucumber/memory
  facts_file: ~/.cucumber/memory/facts.json
  summary_file: ~/.cucumber/memory/last_summary.txt
  max_session_messages: 20
  summarize_keep_recent: 8

logging:
  enabled: true           # Enable file logging
  level: INFO             # DEBUG, INFO, WARNING, ERROR
  verbose: false          # If true, enables DEBUG level
  log_dir: ~/.cucumber/logs  # Where to store logs

workspace: /path/to/your/project
```

### Logging Config

| Field | Description | Default |
|-------|-------------|---------|
| `enabled` | Enable file logging | true |
| `level` | Log level: DEBUG, INFO, WARNING, ERROR | INFO |
| `verbose` | Enable DEBUG level + verbose console | false |
| `log_dir` | Directory for log files | ~/.cucumber/logs |

Log files are rotated automatically (5 MB per file, 3 backups kept).
Exception traces are always logged to `cucumber.log`.

## personality/personality.md

Defines the agent's identity and behavior.

```markdown
# Personality
name: Cucumber
tone: friendly
language: en
greeting: Hi! I'm Cucumber. How can I help you today?
strengths: coding, web research, answering questions
interests: AI, Python, open source
```

### Fields

| Field | Description | Default |
|-------|-------------|---------|
| `name` | Agent's name | Cucumber |
| `tone` | Communication style: casual, friendly, professional, formal | friendly |
| `language` | Response language: en, de | en |
| `greeting` | Default greeting message | "" |
| `strengths` | What the agent is good at | "" |
| `interests` | Topics the agent cares about | "" |

`personality.md` is loaded into the `CORE IDENTITY` block on every model call.
It is not summarized, compressed, or replaced by conversation history. See
[Memory & Personality](Memory.md) for the full preservation contract.

## user/user.md

Stores user information so the agent can personalize interactions.

```markdown
# User
name: David
bio: Python developer
github: https://github.com/DavidSchuchert
portfolio: https://davidschuchert.com
```

### Fields

| Field | Description |
|-------|-------------|
| `name` | User's name |
| `bio` | Short description |
| `github` | GitHub profile URL |
| `portfolio` | Website/portfolio URL |

## Environment Variables

API keys can also be set via environment variables:

| Provider | Environment Variable |
|----------|---------------------|
| MiniMax | `MINIMAX_API_KEY` |
| OpenRouter | `OPENROUTER_API_KEY` |
| DeepSeek | `DEEPSEEK_API_KEY` |
| Ollama | `OLLAMA_BASE_URL` |

The setup wizard currently offers the providers that are registered in code:
MiniMax, OpenRouter, DeepSeek, and Ollama. Ollama does not require an API key.

If an API key is not in `config.yaml`, the system checks the environment.

## Memory Files

| File | Purpose |
|------|---------|
| `memory/facts.json` or `memory/facts.db` | Durable facts from `/remember` |
| `memory/last_summary.txt` | Append-only summary of older sessions |
| `memory/YYYY-MM-DD.md` | Human-readable daily conversation logs |
| `memory/exchanges.db` | Optional structured session log |

Facts are reloaded from disk whenever the prompt is built, so the agent can keep
long-term preferences even if a live session object is missing metadata.
