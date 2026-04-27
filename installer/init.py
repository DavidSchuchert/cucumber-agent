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


def select_provider() -> str:
    """Select a provider."""
    console.print("[bold]1.[/bold] MiniMax (fast, cheap)")
    console.print("[bold]2.[/bold] OpenRouter (hundreds of models)")
    console.print("[bold]3.[/bold] DeepSeek (direct API)")
    console.print("[bold]4.[/bold] NVIDIA NIM (40 req/min free)")
    console.print("[bold]5.[/bold] LM Studio (local)")
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
        return None  # No API key needed for local

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
        console.print(f"  [bold]{i}.[/bold] {desc} [dim]({model_id})[/dim]")

    choice = Prompt.ask(
        "\nSelect model", choices=[str(i) for i in range(1, len(options) + 1)], default="1"
    )
    return options[int(choice) - 1][0]


def create_config(
    provider_name: str,
    display_name: str,
    base_url: str | None,
    api_key: str | None,
    model: str,
) -> dict:
    """Create the configuration dictionary."""
    config = {
        "agent": {
            "provider": provider_name,
            "model": model,
            "temperature": 0.7,
            "max_tokens": None,
            "system_prompt": "You are CucumberAgent, a helpful AI assistant.",
        },
        "providers": {
            provider_name: {
                "api_key": api_key,
                "base_url": base_url,
                "model": model,
            }
        },
    }

    # Ask for workspace
    workspace = Prompt.ask(
        "\nWorkspace directory",
        default=str(Path.cwd()),
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

    # Select provider
    provider_name, display_name, base_url = select_provider()

    # Get API key
    api_key = get_api_key(provider_name, display_name)
    if api_key is None and provider_name != "lmstudio":
        console.print(
            "[yellow]No API key provided. You can set it in config later or use environment variables.[/yellow]"
        )

    # Select model
    model = select_model(provider_name, display_name)

    # Create config
    config = create_config(provider_name, display_name, base_url, api_key, model)

    # Save
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    console.print()
    console.print(
        Panel.fit(
            "[bold green]✅ Setup complete![/bold green]\n\n"
            f"Config saved to [dim]{CONFIG_FILE}[/dim]\n\n"
            "Run [bold]cucumber run[/bold] to start chatting!",
            border_style="green",
        )
    )


if __name__ == "__main__":
    run()
