"""CLI - Read-Eval-Print loop for CucumberAgent."""

from __future__ import annotations

import asyncio
import re
import sys
from collections.abc import AsyncIterator
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from cucumber_agent.agent import Agent
from cucumber_agent.config import Config
from cucumber_agent.session import Session

console = Console()


async def stream_print(stream: AsyncIterator[str]) -> str:
    """Stream chunks and print them as they arrive. Return full text."""
    full = ""
    with console.status("[bold green]Thinking..."):
        async for chunk in stream:
            full += chunk
            console.print(chunk, end="", soft_wrap=True)
    return full


def print_welcome() -> None:
    """Print welcome message."""
    console.print(
        Panel.fit(
            "[bold cyan]🥒 CucumberAgent[/bold cyan]\n\n"
            "A clean, modular AI agent framework.\n\n"
            "Type [bold]/help[/bold] for commands or just chat!",
            border_style="cyan",
        )
    )


def print_help() -> None:
    """Print help message."""
    help_text = """
# Commands

| Command | Description |
|---------|-------------|
| `/help` | Show this help |
| `/exit` | Exit CucumberAgent |
| `/clear` | Clear the conversation |
| `/config` | Show current configuration |
| `/model` | Show current model |
| `/optimize` | Optimize personality based on name |
| `/debug` | Toggle debug view |

Just type normally to chat!
"""
    console.print(Markdown(help_text))


def print_config(config: Config) -> None:
    """Print configuration."""
    agent = config.agent
    config_text = f"""
# Current Config

**Provider:** {agent.provider}
**Model:** {agent.model}
**Temperature:** {agent.temperature}
"""
    console.print(Markdown(config_text))


class CliSession:
    """CLI REPL session."""

    def __init__(self, agent: Agent, config: Config):
        self._agent = agent
        self._config = config
        self._session = Session(id="main", model=config.agent.model)
        self._running = False
        self._waiting_for_optimization_response = False
        self._debug_mode = False

    async def run(self) -> None:
        """Run the REPL."""
        print_welcome()

        # Show model info
        console.print(
            f"[dim]Using {self._config.agent.provider}/{self._config.agent.model}[/dim]\n"
        )

        self._running = True
        while self._running:
            try:
                user_input = await asyncio.to_thread(
                    lambda: console.input(
                        "[bold green]cucumber> [/bold green]" if not self._debug_mode
                        else "[bold red]cucumber [DEBUG]> [/bold red]"
                    )
                )
                await self._handle_input(user_input)
            except KeyboardInterrupt:
                console.print("\n[dim]Use /exit to quit[/dim]")
            except EOFError:
                console.print("\n[bold]Goodbye![/bold]")
                break

    async def _handle_input(self, user_input: str) -> None:
        """Handle user input."""
        if not user_input.strip():
            return

        # Handle commands
        if user_input.startswith("/"):
            await self._handle_command(user_input)
            return

        # Handle optimization response
        if self._waiting_for_optimization_response:
            await self._handle_optimization_response(user_input)
            return

        # Regular chat
        console.print()
        try:
            # Check if this is a greeting and optimization should be offered
            offer_optimization = self._agent.needs_optimization(user_input)

            stream = self._agent.run_stream(self._session, user_input)
            await stream_print(stream)

            console.print()  # newline after streaming

            # After first greeting, offer optimization
            if offer_optimization:
                optimization_offer = self._agent.build_optimization_response(user_input)
                if optimization_offer:
                    console.print(optimization_offer)
                    console.print()
                    self._waiting_for_optimization_response = True

        except Exception as e:
            console.print(f"[bold red]Error:[/bold red] {e}")

    async def _handle_optimization_response(self, user_input: str) -> None:
        """Handle user's response to optimization offer."""
        self._waiting_for_optimization_response = False

        response = user_input.lower().strip()

        # Check for yes/no patterns
        yes_patterns = [r"^ja\b", r"^yes\b", r"^y\b", r"^yo\b", r"^gerne\b", r"^ok\b", r"^okay\b"]
        no_patterns = [r"^nein\b", r"^no\b", r"^n\b", r"^ne\b"]

        if any(re.match(p, response) for p in yes_patterns):
            console.print("\n[dim]✨ Optimizing personality...[/dim]\n")
            suggestions = self._agent.apply_optimization()
            console.print(
                f"[green]✅ Done![/green] Emoji: {suggestions['emoji']}, "
                f"Strengths: {suggestions['strengths']}"
            )
            console.print("\n[dim]Starte neu für effekt! (Ctrl+C + cucumber run)[/dim]\n")

        elif any(re.match(p, response) for p in no_patterns):
            console.print("[dim]Optimierung übersprungen.[/dim]\n")
        else:
            console.print('[dim]Antworte "ja" oder "nein"[/dim]\n')

    async def _handle_command(self, user_input: str) -> None:
        """Handle slash commands."""
        cmd = user_input.strip().lower()

        match cmd:
            case "/help":
                print_help()
            case "/exit" | "/quit":
                console.print("[bold]Goodbye![/bold]")
                self._running = False
            case "/clear":
                self._session = Session(id="main", model=self._config.agent.model)
                console.print("[dim]Conversation cleared[/dim]")
            case "/config":
                print_config(self._config)
            case "/model":
                console.print(f"Model: {self._config.agent.model}")
            case "/optimize":
                await self._run_optimization()
            case "/debug":
                self._debug_mode = not self._debug_mode
                if self._debug_mode:
                    console.print("[red]🔧 Debug mode ON[/red]")
                    self._print_debug_info()
                else:
                    console.print("[dim]Debug mode OFF[/dim]")
            case _:
                console.print(f"[dim]Unknown command: {cmd}[/dim]. Type /help for help.")

    async def _run_optimization(self) -> None:
        """Run optimization manually."""
        from cucumber_agent.agent import suggest_optimization

        pers = self._config.personality
        suggestions = suggest_optimization(pers.name, pers.tone, pers.greeting)

        console.print(f'\n[bold]✨ Optimizing for "{pers.name}"...[/bold]\n')
        console.print(f"  Emoji: {suggestions['emoji']}")
        console.print(f"  Greeting: {suggestions['greeting']}")
        console.print(f"  Strengths: {suggestions['strengths']}\n")

        self._agent.apply_optimization()
        console.print("[green]✅ Personality optimized![/green]\n")
        console.print("[dim]Restart: Ctrl+C then 'cucumber run'[/dim]\n")

    def _print_debug_info(self) -> None:
        """Print debug information."""
        pers = self._config.personality
        ctx = self._config.context
        agent = self._config.agent

        console.print("\n[bold]🔧 Debug Info[/bold]")
        console.print("  Personality:")
        console.print(f"    name: {pers.name}")
        console.print(f"    emoji: {pers.emoji}")
        console.print(f"    tone: {pers.tone}")
        console.print(f"    language: {pers.language}")
        console.print(f"    greeting: {pers.greeting[:50] if pers.greeting else 'none'}...")
        console.print("  Agent:")
        console.print(f"    provider: {agent.provider}")
        console.print(f"    model: {agent.model}")
        console.print(f"    temperature: {agent.temperature}")
        console.print("  Context:")
        console.print(f"    max_tokens: {ctx.max_tokens}")
        console.print(f"    remember_last: {ctx.remember_last}")
        console.print(f"  Session messages: {len(self._session.messages)}")
        console.print()


async def run_cli() -> None:
    """Run the CLI session."""
    config = Config.load()
    agent = Agent.from_config(config)
    session = CliSession(agent, config)
    await session.run()


def run_init() -> None:
    """Run the setup wizard."""
    import os
    import subprocess

    possible_paths = [
        os.path.join(os.path.dirname(__file__), "..", "..", "installer", "init.py"),
    ]

    installer_path = None
    for path in possible_paths:
        expanded = os.path.expanduser(path)
        resolved = os.path.normpath(expanded)
        if os.path.exists(resolved):
            installer_path = resolved
            break

    if installer_path and os.path.exists(installer_path):
        result = subprocess.run([sys.executable, installer_path])
        sys.exit(result.returncode)
    else:
        console.print("[bold red]Error:[/bold red] Could not find installer. Run from project directory.")
        sys.exit(1)


def run_update() -> None:
    """Update CucumberAgent from GitHub."""
    import subprocess

    install_dir = Path.home() / ".cucumber-agent"

    console.print("[bold]🔄 Updating CucumberAgent...[/bold]\n")

    if not install_dir.exists():
        console.print("[red]ERROR:[/red] Installation not found at ~/.cucumber-agent")
        console.print("Run the installer first: curl ... | sh")
        sys.exit(1)

    try:
        console.print("→ Pulling latest from GitHub...")
        result = subprocess.run(
            ["git", "pull", "origin", "main"],
            cwd=install_dir,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            console.print("→ Reinstalling package...")
            subprocess.run(["uv", "tool", "install", "-e", "."], cwd=install_dir)
            console.print("\n[green]✅ Update complete![/green]\n")
        else:
            console.print(f"[red]Git pull failed:[/red] {result.stderr}")
            sys.exit(1)
    except Exception as e:
        console.print(f"[red]Update failed:[/red] {e}")
        sys.exit(1)


async def run_config_cmd() -> None:
    """Show configuration."""
    config = Config.load()
    print_config(config)


def main() -> None:
    """Main entry point."""
    # Handle subcommands
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "init":
            run_init()
            return
        elif cmd == "config":
            asyncio.run(run_config_cmd())
            return
        elif cmd == "update":
            run_update()
            return
        elif cmd in ("--help", "-h"):
            console.print("[bold]CucumberAgent CLI[/bold]\n")
            console.print("Commands:")
            console.print("  [cyan]cucumber run[/cyan]     Start chat session")
            console.print("  [cyan]cucumber init[/cyan]    Run setup wizard")
            console.print("  [cyan]cucumber config[/cyan]  Show configuration")
            console.print("  [cyan]cucumber --help[/cyan]  Show this help")
            return

    try:
        asyncio.run(run_cli())
    except KeyboardInterrupt:
        pass
