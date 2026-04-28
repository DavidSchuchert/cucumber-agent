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
from rich.syntax import Syntax

from cucumber_agent.agent import Agent
from cucumber_agent.config import Config
from cucumber_agent.session import Session
from cucumber_agent.tools.registry import ToolRegistry

console = Console()


async def stream_print(stream: AsyncIterator[str]) -> str:
    """Stream chunks and print them as they arrive. Return full text."""
    full = ""
    in_code_block = False
    code_buffer = ""

    async for chunk in stream:
        full += chunk

        # Handle code blocks specially
        if not in_code_block and "```" in chunk:
            parts = chunk.split("```")
            if len(parts) >= 3:
                console.print(parts[0], end="")
                code = parts[1].rstrip()
                lang = "text"
                if code:
                    syntax = Syntax(code, lexer=lang, theme="monokai", line_numbers=True)
                    console.print(syntax)
                console.print(parts[2], end="")
                continue

        if not in_code_block and chunk.strip().startswith("```"):
            in_code_block = True
            code_buffer = chunk
        elif in_code_block:
            code_buffer += chunk
            if "```" in chunk:
                lines = code_buffer.split("\n", 1)
                lang = lines[0].strip().strip("`") or "text"
                code = lines[1].rstrip() if len(lines) > 1 else ""
                if code:
                    syntax = Syntax(code, lexer=lang, theme="monokai", line_numbers=True)
                    console.print(syntax)
                in_code_block = False
                code_buffer = ""
        else:
            console.print(chunk, end="")

    console.print()  # newline after streaming
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


def parse_personality_update(text: str) -> tuple[dict, str] | None:
    """Parse PERSONITY_UPDATE:emoji=x,... from AI response. Returns (params, explanation)."""
    import re

    lines = text.strip().split("\n")
    explanation = ""
    params = None

    for i, line in enumerate(lines):
        line = line.strip()
        if line.startswith("PERSONALITY_UPDATE:"):
            # Extract explanation from previous line(s)
            if i > 0:
                # Collect explanation lines before the update
                explanation_parts = []
                for j in range(i - 1, -1, -1):
                    prev = lines[j].strip()
                    if prev.startswith("KEINE_VERBESSERUNG"):
                        break
                    if prev.startswith("PERSONALITY_UPDATE"):
                        break
                    explanation_parts.insert(0, prev)
                explanation = " ".join(explanation_parts)

            # Parse params
            match = re.match(r"PERSONALITY_UPDATE:(.+)", line)
            if match:
                params = {}
                for part in match.group(1).split(","):
                    if "=" in part:
                        key, value = part.split("=", 1)
                        params[key.strip()] = value.strip()
            break
        elif line.startswith("KEINE_VERBESSERUNG"):
            # No improvement, get explanation from following lines
            explanation = " ".join(line.strip() for line in lines[i + 1 : i + 3] if line.strip())
            return None, explanation

    if params:
        return params, explanation
    return None


def apply_personality_update(params: dict, config: Config) -> None:
    """Apply personality update from parsed params."""
    pers = config.personality

    if "emoji" in params:
        pers.emoji = params["emoji"]
    if "greeting" in params:
        pers.greeting = params["greeting"]
    if "tone" in params:
        pers.tone = params["tone"]
    if "strengths" in params:
        pers.strengths = params["strengths"]
    if "interests" in params:
        pers.interests = params["interests"]

    # Save to personality.md
    pers.to_markdown(config.config_dir / "personality" / "personality.md")
    # Update system prompt in agent config
    config.agent.system_prompt = pers.to_system_prompt()
    config.save()


class CliSession:
    """CLI REPL session."""

    def __init__(self, agent: Agent, config: Config):
        self._agent = agent
        self._config = config
        self._session = Session(id="main", model=config.agent.model)
        self._running = False
        self._waiting_for_optimization_response = False
        self._debug_mode = False
        self._pending_tool_call: dict | None = None  # For user confirmation

        # Import tools
        from cucumber_agent import tools  # noqa: F401

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

        # Handle tool call approval
        if self._pending_tool_call:
            await self._handle_tool_approval(user_input)
            return

        # Regular chat
        console.print()
        try:
            # Check if this is a greeting and optimization should be offered
            offer_optimization = self._agent.needs_optimization(user_input)

            # Use non-streaming to properly handle tool calls
            response = await self._agent.run_with_tools(self._session, user_input)

            # Check for tool calls FIRST
            if response.tool_calls:
                # Suppress verbose text when tool calls present - just show minimal info
                if response.content and response.content.strip():
                    # Only show if it looks like actual useful content, not "I'll now..."
                    words = response.content.lower()
                    if not any(w in words for w in ['ich', 'i will', 'let me', 'now', 'jetzt', 'werde']):
                        console.print(response.content)
            else:
                console.print(response.content)
                for tc in response.tool_calls:
                    tool = tc.name
                    args = tc.arguments
                    console.print()
                    self._print_tool_call({
                        "name": tool,
                        "arguments": args,
                    })
                    self._pending_tool_call = {
                        "name": tool,
                        "arguments": args,
                    }
                    return

            console.print()  # newline after response

            # After first greeting, offer optimization
            if offer_optimization:
                pers = self._config.personality
                console.print("\n[bold cyan]──────[/bold cyan]")
                console.print(f"[bold]{pers.emoji} Möchtest du, dass ich meine Persönlichkeit optimiere?[/bold]")
                console.print("    Ich kann Emoji, Greeting und Stärken basierend auf meinem Namen anpassen.")
                console.print("    Antworte mit: [bold]ja[/bold] zum Optimieren oder [bold]nein[/bold] zum Überspringen")
                console.print("[bold cyan]──────[/bold cyan]\n")
                self._waiting_for_optimization_response = True

        except Exception as e:
            console.print(f"[bold red]Error:[/bold red] {e}")

    async def _handle_optimization_response(self, user_input: str) -> None:
        """Handle user's response to optimization offer."""
        self._waiting_for_optimization_response = False

        response = user_input.lower().strip()

        # Check if user declined
        no_patterns = [r"^nein\b", r"^no\b", r"^n\b", r"^ne\b", r"^überspring\b", r"^skip\b", r"^nee\b"]
        if any(re.match(p, response) for p in no_patterns):
            console.print("[dim]OK, überspringe Optimierung.[/dim]\n")
            return

        # User wants optimization - check if response contains positive intent
        positive_patterns = [r"^ja\b", r"^yes\b", r"^optimier", r"^ok\b", r"^okay\b", r"^gerne\b", r"^yo\b"]
        if not any(re.match(p, response) for p in positive_patterns):
            console.print("[dim]Verstanden, keine Optimierung.[/dim]\n")
            return

        # User wants optimization - send special prompt to AI
        console.print("\n[dim]✨ Analyzing my name and optimizing...[/dim]\n")

        # Read current personality file
        personality_file = self._config.config_dir / "personality" / "personality.md"
        current_personality = personality_file.read_text() if personality_file.exists() else ""

        pers = self._config.personality
        optimization_prompt = f"""You are analyzing a personality configuration to improve it.

Current personality:
{current_personality}

Your task:
1. Read the name "{pers.name}" - think about what this name evokes
2. Suggest BETTER values than what's currently there:
   - emoji: Pick an emoji that PERFECTLY matches this name (be creative, use unicode)
   - greeting: Create a unique, catchy greeting (max 15 words)
   - strengths: Suggest 2-3 strengths that fit this persona

Output format:
First line: BRIEF explanation of what you changed and why (1-2 sentences)
Second line: PERSONALITY_UPDATE:emoji=X,greeting=Y,strengths=Z

If you genuinely think the current values are already good, say:
KEINE_VERBESSERUNG
Then briefly explain why the current values work well for this name.

Do NOT echo back the current values. Actually analyze and suggest improvements."""

        # Clear the session and send this prompt to the AI
        optimization_session = Session(id="optimize", model=self._config.agent.model)
        stream = self._agent.run_stream(optimization_session, optimization_prompt)
        full_response = await stream_print(stream)

        console.print()

        # Parse and apply any personality update from AI response
        result = parse_personality_update(full_response)
        if result:
            update_params, explanation = result
            apply_personality_update(update_params, self._config)

            # Verify changes were saved
            personality_file = self._config.config_dir / "personality" / "personality.md"
            personality_file.read_text()  # Will raise if can't read

            console.print(f"\n[dim]{explanation}[/dim]")
            console.print("\n[green]✅ Personality optimized! Changes saved to personality.md[/green]\n")
            console.print("[dim]Restart: Ctrl+C + cucumber run[/dim]\n")
        else:
            explanation = result[1] if result else "No improvements suggested."
            console.print("\n[dim]OK, nothing to improve.[/dim]\n")

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
            case "/debug":
                self._debug_mode = not self._debug_mode
                if self._debug_mode:
                    console.print("[red]🔧 Debug mode ON[/red]")
                    self._print_debug_info()
                else:
                    console.print("[dim]Debug mode OFF[/dim]")
            case _:
                console.print(f"[dim]Unknown command: {cmd}[/dim]. Type /help for help.")

    async def _handle_tool_approval(self, user_input: str) -> None:
        """Handle user's response to a tool call."""
        tool_call = self._pending_tool_call
        if not tool_call:
            console.print("[dim]No pending tool call.[/dim]\n")
            return

        choice = user_input.strip()
        tool_name = tool_call.get("name", "unknown")
        args = tool_call.get("arguments", {})
        command = args.get("command", "")

        if choice == "1":
            # Execute
            self._pending_tool_call = None
            console.print(f"\n[dim]⚡ Executing {tool_name}...[/dim]\n")
            result = await ToolRegistry.execute(tool_name, **args)

            # Add tool result to session so AI can see it
            from cucumber_agent.session import Message, Role
            tool_result_msg = Message(
                role=Role.USER,
                content=f"[TOOL_RESULT] {tool_name}: {result.output if result.success else 'ERROR: ' + (result.error or result.output)}"
            )
            self._session.messages.append(tool_result_msg)

            if result.success:
                console.print("[green]✓ Done[/green]\n")
                output_text = result.output[:500] if len(result.output) > 500 else result.output
                if output_text.strip():
                    console.print(f"[dim]{output_text}[/dim]\n")
                # Now let AI respond to the result
                resp = await self._agent.run_with_tools(self._session, "")
                if resp.tool_calls:
                    for tc in resp.tool_calls:
                        self._print_tool_call({"name": tc.name, "arguments": tc.arguments})
                        self._pending_tool_call = {"name": tc.name, "arguments": tc.arguments}
                        return
                else:
                    console.print(resp.content)
                    console.print()
            else:
                console.print(f"[red]✗ Error:[/red] {result.error or result.output}\n")
                # Let AI respond to the error
                resp = await self._agent.run_with_tools(self._session, "")
                if resp.tool_calls:
                    for tc in resp.tool_calls:
                        self._print_tool_call({"name": tc.name, "arguments": tc.arguments})
                        self._pending_tool_call = {"name": tc.name, "arguments": tc.arguments}
                        return
                else:
                    console.print(resp.content)
                    console.print()

        elif choice == "2":
            # Cancel
            self._pending_tool_call = None
            console.print("[dim]Tool call cancelled.[/dim]\n")

        elif choice == "3":
            # Edit command - ask for new command
            console.print(f"[dim]Current:[/dim] {command}")
            new_cmd = await asyncio.to_thread(
                lambda: console.input("[yellow]Enter new command: [/yellow]")
            )
            if new_cmd.strip():
                tool_call["arguments"]["command"] = new_cmd.strip()
                self._pending_tool_call = tool_call
                console.print()
                self._print_tool_call(tool_call)
                return  # Wait for next choice
            else:
                console.print("[dim]Command unchanged.[/dim]\n")
                console.print("[1] Execute [2] Cancel [3] Edit again")

        else:
            self._pending_tool_call = None
            console.print("[dim]Invalid choice. Tool call cancelled.[/dim]\n")

    def _print_tool_call(self, tool_call: dict) -> None:
        """Display a tool call with approval options."""
        tool_name = tool_call.get("name", "unknown")
        args = tool_call.get("arguments", {})
        command = args.get("command", "")
        reason = args.get("reason", "No description provided")

        console.print(
            Panel(
                f"[bold]Tool:[/bold] {tool_name}\n"
                f"[bold]Command:[/bold] {command}\n"
                f"[bold]Reason:[/bold] {reason}",
                title="⚡ Tool Call Approval Required",
                border_style="yellow",
            )
        )
        console.print("[bold]Choose:[/bold]")
        console.print("  [1] Execute")
        console.print("  [2] Cancel")
        console.print("  [3] Edit command")
        console.print()

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
