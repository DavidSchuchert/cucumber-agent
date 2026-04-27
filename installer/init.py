#!/usr/bin/env python3
"""Interactive setup wizard for CucumberAgent."""

import os
from pathlib import Path

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

console = Console()
CONFIG_DIR = Path.home() / ".cucumber"
CONFIG_FILE = CONFIG_DIR / "config.yaml"


def print_banner() -> None:
    console.print(
        Panel.fit(
            "[bold cyan]🥒 CucumberAgent Setup[/bold cyan]\n\nLet's get you set up!",
            border_style="cyan",
        )
    )
    console.print()


def ask_agent_name() -> str:
    """Ask for agent's name."""
    console.print("[bold]First, let's give your AI assistant a name![/bold]\n")

    # Show suggestions
    suggestions = ["Cucumber", "Herbert", "Buddy", "Assistant", "Max"]
    console.print("[dim]Suggestions:[/dim] " + ", ".join(suggestions))
    console.print()

    agent_name = Prompt.ask(
        "What's the AI assistant's name?",
        default="Cucumber",
    )
    return agent_name.strip() or "Cucumber"


def enhance_personality(agent_name: str, personality: dict) -> dict:
    """Enhance personality with AI-suggested optimizations based on name."""
    # Suggest emoji based on name patterns
    emoji_map = {
        # Tech/coding names
        "code": "💻", "bit": "🖥️", "byte": "⚡", "chip": "🔧",
        "pixel": "🎨", "debug": "🐛", "syntax": "📝",
        # Friendly names
        "buddy": "🤝", "friend": "😊", "pal": "🙂", "max": "🎯",
        # Nature names
        "cucumber": "🥒", "gherkin": "🥒", "pickle": "🥒",
        "herb": "🌿", "sage": "🧙", "mint": "🍃",
        # Professional names
        "claude": "🧠", "atlas": "🌍", "neo": "🕶️", "cipher": "🔐",
        # Cute names
        "blob": "🟢", "wizard": "🧙‍♂️", "mage": "✨",
    }

    name_lower = agent_name.lower()
    emoji = emoji_map.get(name_lower, "🤖")

    # Auto-suggest greeting based on name and tone
    tone = personality.get("tone", "friendly")
    tone_greetings = {
        "casual": f"Hey! I'm {agent_name}. What's up? 😎",
        "friendly": f"Hi! I'm {agent_name}. Great to see you! 👋",
        "professional": f"Hello. I'm {agent_name}. How may I assist you today?",
        "formal": f"Good day. I am {agent_name}. At your service.",
    }
    suggested_greeting = tone_greetings.get(tone, f"Hi! I'm {agent_name}.")

    # Suggest strengths based on name (simple heuristic)
    name_strengths = {
        "code": "programming, debugging, code review, software architecture",
        "herb": "research, writing, analysis, knowledge synthesis",
        "sage": "wisdom, problem-solving, strategic thinking, mentorship",
        "buddy": "support, collaboration, communication, encouragement",
        "claude": "reasoning, analysis, writing, creative problem-solving",
    }

    suggested_strengths = name_strengths.get(name_lower, "coding, problem-solving, research, communication")

    console.print(f"\n[bold cyan]✨ Optimizing personality for '{agent_name}'...[/bold cyan]")
    console.print(f"  Suggested emoji: {emoji}")
    console.print(f"  Suggested greeting: {suggested_greeting}")
    console.print(f"  Suggested strengths: {suggested_strengths}")

    # Ask if user wants to use suggested values
    if Confirm.ask(f"\nUse these suggested values for {agent_name}?", default=True):
        personality["greeting"] = suggested_greeting
        personality["strengths"] = suggested_strengths
        # Store emoji in extra field
        personality["emoji"] = emoji
    else:
        # User keeps their custom values, still suggest emoji
        if Confirm.ask("Add suggested emoji?", default=True):
            personality["emoji"] = emoji

    return personality


def ask_personality(agent_name: str) -> dict:
    """Ask about personality and preferences."""
    console.print(f"\n[bold]Now let's configure {agent_name}'s personality![/bold]\n")

    personality = {}

    # Language - NEW
    console.print("[bold]Language:[/bold]")
    console.print("[dim]   1.[/dim] English")
    console.print("[dim]   2.[/dim] German (Deutsch)")
    console.print("[dim]   3.[/dim] Other (specify)")

    lang_choice = Prompt.ask(
        "Which language should I speak?",
        default="1",
    )

    lang_map = {"1": "en", "2": "de"}
    if lang_choice in lang_map:
        personality["language"] = lang_map[lang_choice]
    else:
        personality["language"] = "en"

    console.print()

    # Tone - custom input allowed
    console.print("[bold]Communication style:[/bold]")
    console.print("[dim]   1.[/dim] casual")
    console.print("[dim]   2.[/dim] friendly")
    console.print("[dim]   3.[/dim] professional")
    console.print("[dim]   4.[/dim] formal")
    console.print("[dim]   5.[/dim] [bold]custom[/bold] (type your own)")

    tone_choice = Prompt.ask(
        "Choose a tone (or type custom)",
        default="friendly",
    )

    # Check if it's a number choice
    tone_map = {"1": "casual", "2": "friendly", "3": "professional", "4": "formal"}
    if tone_choice in tone_map:
        personality["tone"] = tone_map[tone_choice]
    else:
        personality["tone"] = tone_choice.strip() if tone_choice.strip() else "friendly"

    console.print()

    # Helper function for custom prompts
    def custom_prompt(label: str, suggestion: str) -> str:
        console.print(f"[dim]Suggestion:[/dim] {suggestion}")
        result = Prompt.ask(label, default=suggestion)
        return result.strip() if result.strip() else suggestion

    # Greeting
    default_greeting = f"Hi! I'm {agent_name}. How can I help you today?"
    personality["greeting"] = custom_prompt("How should I greet users?", default_greeting)

    # Strengths
    default_strengths = "coding, web research, answering questions, problem-solving"
    personality["strengths"] = custom_prompt(
        "What are my strengths? (comma separated)", default_strengths
    )

    # Interests (optional)
    console.print()
    if Confirm.ask("Should I have specific interests or expertise?", default=True):
        personality["interests"] = custom_prompt(
            "What topics interest me?", "AI, technology, programming, open source"
        )
    else:
        personality["interests"] = ""

    # Step: Auto-enhance personality with AI suggestions
    personality = enhance_personality(agent_name, personality)

    return personality


def ask_user_info(agent_name: str) -> dict:
    """Ask about the user."""
    console.print(f"\n[bold]Tell me about yourself (so {agent_name} can help better):[/bold]\n")

    user_info = {}

    user_name = Prompt.ask(
        "What's your name?",
        default="",
    )
    user_info["name"] = user_name.strip() if user_name.strip() else ""

    user_bio = Prompt.ask(
        "What should I know about you? (optional)",
        default="",
    )
    user_info["bio"] = user_bio.strip() if user_bio.strip() else ""

    console.print()
    console.print("[bold]Online presence (optional):[/bold]")

    github = Prompt.ask(
        "GitHub URL",
        default="",
    )
    user_info["github"] = github.strip() if github.strip() else ""

    portfolio = Prompt.ask(
        "Portfolio/Website URL",
        default="",
    )
    user_info["portfolio"] = portfolio.strip() if portfolio.strip() else ""

    return user_info


def ask_preferences() -> dict:
    """Ask about agent behavior."""
    console.print("\n[bold]Behavior preferences:[/bold]\n")

    preferences = {}

    preferences["can_search_web"] = Confirm.ask(
        "Should I search the web when needed?",
        default=True,
    )

    preferences["can_code"] = Confirm.ask(
        "Should I help with coding tasks?",
        default=True,
    )

    preferences["can_remember"] = Confirm.ask(
        "Should I remember things between conversations?",
        default=True,
    )

    return preferences


def select_provider() -> tuple:
    """Select a provider."""
    console.print("\n[bold]Choose your AI provider:[/bold]")
    console.print("[dim]1.[/dim] MiniMax (fast, cheap)")
    console.print("[dim]2.[/dim] OpenRouter (many models)")
    console.print("[dim]3.[/dim] DeepSeek (direct API)")
    console.print("[dim]4.[/dim] NVIDIA NIM (40 req/min free)")
    console.print("[dim]5.[/dim] LM Studio (local)")
    console.print()

    choice = Prompt.ask(
        "Which provider?",
        choices=["1", "2", "3", "4", "5"],
        default="1",
    )

    providers = {
        "1": ("minimax", "MiniMax", "https://api.minimax.io/anthropic"),
        "2": ("openrouter", "OpenRouter", "https://openrouter.ai/api/v1"),
        "3": ("deepseek", "DeepSeek", "https://api.deepseek.com"),
        "4": ("nvidia_nim", "NVIDIA NIM", "https://integrate.api.nvidia.com/v1"),
        "5": ("lmstudio", "LM Studio", "http://localhost:1234/v1"),
    }

    return providers.get(choice, ("minimax", "MiniMax", "https://api.minimax.io/anthropic"))


def get_api_key(provider_name: str, display_name: str) -> str | None:
    """Get API key from user or environment."""
    env_map = {
        "minimax": "MINIMAX_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "nvidia_nim": "NVIDIA_NIM_API_KEY",
    }

    env_var = env_map.get(provider_name)
    if env_var and env_var in os.environ:
        console.print(f"[dim]Using {env_var} from environment[/dim]")
        return os.environ[env_var]

    if provider_name == "lmstudio":
        return None

    api_key = Prompt.ask(
        f"Enter your {display_name} API key",
        password=True,
    )
    return api_key if api_key.strip() else None


def select_model(provider_name: str, display_name: str) -> str:
    """Select a model."""
    models = {
        "minimax": [
            ("MiniMax-M2.7", "MiniMax M2.7 (fast, 204k context)"),
        ],
        "openrouter": [
            ("openai/gpt-4o-mini", "GPT-4o Mini (fast, cheap)"),
            ("openai/gpt-4o", "GPT-4o (powerful)"),
            ("anthropic/claude-3.5-haiku", "Claude 3.5 Haiku (fast)"),
            ("anthropic/claude-3.5-sonnet", "Claude 3.5 Sonnet (balanced)"),
            ("google/gemini-2.0-flash", "Gemini 2.0 Flash (fast)"),
            ("deepseek/deepseek-chat-v3-0324", "DeepSeek V3 (powerful)"),
        ],
        "nvidia_nim": [
            ("nvidia_nim/meta/llama-4-mega-8b-instruct", "Llama 4 Mega (fast)"),
            ("nvidia_nim/meta/llama-4-maverick-17b-128e-instruct", "Llama 4 Maverick"),
        ],
        "deepseek": [
            ("deepseek-chat", "DeepSeek Chat"),
            ("deepseek-reasoner", "DeepSeek Reasoner"),
        ],
        "lmstudio": [
            ("local-model", "Local Model (any loaded in LM Studio)"),
        ],
    }

    options = models.get(provider_name, models["openrouter"])

    console.print(f"\n[bold]Available {display_name} models:[/bold]")
    for i, (model_id, desc) in enumerate(options, 1):
        console.print(f"  [dim]{i}.[/dim] {desc} [dim]({model_id})[/dim]")

    choice = Prompt.ask(
        "Select model",
        choices=[str(i) for i in range(1, len(options) + 1)],
        default="1",
    )
    return options[int(choice) - 1][0]


def create_personality_file(
    agent_name: str,
    personality: dict,
) -> None:
    """Create personality.md file."""
    from pathlib import Path

    personality_dir = Path.home() / ".cucumber" / "personality"
    personality_dir.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Personality",
        f"name: {agent_name}",
        f"emoji: {personality.get('emoji', '🤖')}",
        f"tone: {personality.get('tone', 'friendly')}",
        f"language: {personality.get('language', 'en')}",
        f"greeting: {personality.get('greeting', '')}",
        f"strengths: {personality.get('strengths', '')}",
        f"interests: {personality.get('interests', '')}",
        "",
    ]

    personality_file = personality_dir / "personality.md"
    personality_file.write_text("\n".join(lines))


def build_system_prompt(
    agent_name: str, personality: dict, user_info: dict, preferences: dict
) -> str:
    """Build the system prompt from all collected info."""
    parts = []

    # Language instruction - CRITICAL
    lang = personality.get("language", "en")
    lang_map = {"en": "English", "de": "German"}
    language_name = lang_map.get(lang, lang)
    parts.append(f"I ALWAYS communicate in {language_name}. ALL my responses must be in {language_name}.")

    # Core identity
    parts.append(f"My name is {agent_name}.")

    # Tone
    tone = personality.get("tone", "friendly")
    tone_desc = {
        "casual": "I'm casual and relaxed in my communication.",
        "friendly": "I'm warm and friendly in my communication.",
        "professional": "I'm professional and concise in my communication.",
        "formal": "I'm formal and respectful in my communication.",
    }
    parts.append(tone_desc.get(tone, f"I communicate in a {tone} manner."))

    # Greeting
    if personality.get("greeting"):
        parts.append(f'My typical greeting is: "{personality["greeting"]}"')

    # Strengths
    if personality.get("strengths"):
        parts.append(f"My strengths include: {personality['strengths']}.")

    # Interests
    if personality.get("interests"):
        parts.append(f"I'm particularly interested in: {personality['interests']}.")

    # User info
    if user_info.get("name"):
        parts.append(f"My human's name is {user_info['name']}.")

    if user_info.get("bio"):
        parts.append(f"About my human: {user_info['bio']}")

    if user_info.get("github"):
        parts.append(f"My human's GitHub: {user_info['github']}")

    if user_info.get("portfolio"):
        parts.append(f"My human's portfolio: {user_info['portfolio']}")

    # Behavior
    if preferences.get("can_search_web"):
        parts.append("I can and should search the web when needed to help my human.")

    if preferences.get("can_code"):
        parts.append("I help with coding tasks when asked.")

    if preferences.get("can_remember"):
        parts.append("I can remember context from our conversation to provide better help.")

    # Always
    parts.append("I'm here to help my human with whatever they need!")

    return " ".join(parts)


def create_user_file(user_info: dict) -> None:
    """Create user.md file."""
    from pathlib import Path

    user_dir = Path.home() / ".cucumber" / "user"
    user_dir.mkdir(parents=True, exist_ok=True)

    lines = [
        "# User",
        f"name: {user_info.get('name', '')}",
        f"bio: {user_info.get('bio', '')}",
        f"github: {user_info.get('github', '')}",
        f"portfolio: {user_info.get('portfolio', '')}",
        "",
    ]

    user_file = user_dir / "user.md"
    user_file.write_text("\n".join(lines))


def create_config(
    agent_name: str,
    provider_name: str,
    base_url: str | None,
    api_key: str | None,
    model: str,
    personality: dict,
    user_info: dict,
    preferences: dict,
) -> dict:
    """Create the configuration dictionary."""
    # Build system prompt from personality
    system_prompt = build_system_prompt(agent_name, personality, user_info, preferences)

    config = {
        "agent": {
            "provider": provider_name,
            "model": model,
            "temperature": 0.7,
            "max_tokens": None,
            "system_prompt": system_prompt,
        },
        "providers": {
            provider_name: {
                "api_key": api_key,
                "base_url": base_url,
                "model": model,
            }
        },
        # Personality now in ~/.cucumber/personality/personality.md
        # User info now in ~/.cucumber/user/user.md
        "preferences": preferences,
        "context": {
            "max_tokens": 8000,
            "remember_last": 10,
        },
    }

    # Ask for workspace
    workspace = Prompt.ask(
        "\nWorkspace directory",
        default=str(Path.home()),
    )
    if workspace.strip():
        config["workspace"] = str(Path(workspace.strip()).expanduser().resolve())

    return config


def run() -> None:
    """Run the setup wizard."""
    print_banner()

    # Check if already configured
    if CONFIG_FILE.exists():
        console.print(f"[dim]Found existing config at {CONFIG_FILE}[/dim]")
        if Confirm.ask("Overwrite existing config?"):
            pass
        else:
            console.print("[dim]Keeping existing config. Run 'cucumber run' to start.[/dim]")
            return

    # Step 1: Agent name
    agent_name = ask_agent_name()

    # Step 2: Personality
    personality = ask_personality(agent_name)

    # Step 3: User info
    user_info = ask_user_info(agent_name)

    # Step 4: Preferences
    preferences = ask_preferences()

    # Step 5: Provider
    console.print()
    provider_name, display_name, base_url = select_provider()

    # Step 6: API key
    api_key = get_api_key(provider_name, display_name)
    if api_key is None and provider_name != "lmstudio":
        console.print("[yellow]No API key provided. You can set it in config later.[/yellow]")

    # Step 7: Model
    model = select_model(provider_name, display_name)

    # Step 8: Create and save config
    config = create_config(
        agent_name, provider_name, base_url, api_key, model, personality, user_info, preferences
    )

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    # Step 9: Create personality.md and user.md
    create_personality_file(agent_name, personality)
    create_user_file(user_info)

    console.print()
    console.print(
        Panel.fit(
            f"[bold green]✅ Setup complete![/bold green]\n\n"
            f"Hello! I'm {agent_name}!\n\n"
            f"Config saved to [dim]{CONFIG_FILE}[/dim]\n\n"
            "Run [bold]cucumber run[/bold] to start chatting!",
            border_style="green",
        )
    )


if __name__ == "__main__":
    run()
