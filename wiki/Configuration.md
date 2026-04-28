# Configuration

CucumberAgent uses a structured directory layout under `~/.cucumber/`:

```
~/.cucumber/
├── config.yaml              # Main config
├── personality/
│   └── personality.md       # Agent personality
├── user/
│   └── user.md              # User information
└── memory/                  # (future) Conversation memory
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
    base_url: https://api.minimax.io/anthropic
    model: MiniMax-M2.7

preferences:
  can_search_web: true
  can_code: true
  can_remember: true
  smart_retry: true       # Auto-retry READ commands on path errors

context:
  max_tokens: 8000        # Max tokens for context window
  remember_last: 10       # Keep last N messages

workspace: /path/to/your/project
```

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
| NVIDIA NIM | `NVIDIA_NIM_API_KEY` |

If an API key is not in `config.yaml`, the system checks the environment.