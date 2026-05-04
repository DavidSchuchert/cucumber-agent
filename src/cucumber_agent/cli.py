"""CLI - Read-Eval-Print loop for CucumberAgent."""
from __future__ import annotations
import asyncio
import os
import re
import sys
from collections.abc import AsyncIterator
from difflib import get_close_matches
from pathlib import Path

import httpx
from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.styles import Style as PtkStyle
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from cucumber_agent.agent import Agent
from cucumber_agent.autopilot import (
    AutopilotState,
    AutopilotStore,
    create_plan,
    parse_autopilot_args,
    report_text,
    run_plan,
    status_text,
)
from cucumber_agent.config import Config
from cucumber_agent.logging_config import get_logger, setup_logging
from cucumber_agent.memory import FactsStore, SessionLogger
from cucumber_agent.session import Message as SessionMessage
from cucumber_agent.session import Role as SessionRole
from cucumber_agent.session import Session
from cucumber_agent.skills import Skill, SkillLoader, SkillRunner
from cucumber_agent.tools.registry import ToolRegistry
from cucumber_agent.workspace import WorkspaceDetector

logger = get_logger("cli")

_COMMAND_PUNCTUATION = ".,;:!?"
STATIC_SLASH_COMMANDS = [
    "/help",
    "/exit",
    "/quit",
    "/clear",
    "/config",
    "/model",
    "/update",
    "/debug",
    "/optimize",
    "/memory",
    "/context",
    "/autopilot",
    "/autoapprove",
    "/compact",
    "/pin",
    "/unpin",
    "/cost",
    "/remember",
    "/forget",
    "/skills",
    "/tools",
    "/history",
    "/undo",
    "/export",
]


def _normalize_command_word(word: str) -> str:
    return word.strip().rstrip(_COMMAND_PUNCTUATION).lower()


def _skill_command_candidates(skill: Skill) -> list[str]:
    aliases = getattr(skill, "aliases", None) or []
    return [skill.command, *aliases]


def _completion_commands(skill_loader: SkillLoader) -> list[str]:
    """Commands shown in slash completion.

    Aliases remain executable, but hiding them from completion prevents one
    skill from appearing multiple times in the prompt suggestions.
    """
    return sorted(set(STATIC_SLASH_COMMANDS + [skill.command for skill in skill_loader.skills]))


def _resolve_skill_invocation(user_input: str, skill_loader: SkillLoader) -> tuple[Skill, str] | None:
    """Resolve exact skill command or alias, tolerating punctuation on command words."""
    words = user_input.strip().split()
    if not words:
        return None

    candidates: list[tuple[int, str, Skill]] = []
    for skill in skill_loader.skills:
        for command in _skill_command_candidates(skill):
            candidates.append((len(command.split()), command, skill))

    for word_count, command, skill in sorted(candidates, reverse=True):
        if len(words) < word_count:
            continue
        input_command = " ".join(_normalize_command_word(w) for w in words[:word_count])
        candidate_command = " ".join(_normalize_command_word(w) for w in command.split())
        if input_command == candidate_command:
            return skill, " ".join(words[word_count:]).strip()

    return None


def _command_suggestion(
    user_input: str,
    skill_loader: SkillLoader,
    static_commands: list[str],
) -> str | None:
    first_word = user_input.strip().split(None, 1)[0] if user_input.strip() else ""
    normalized = _normalize_command_word(first_word)
    commands = list(static_commands)
    for skill in skill_loader.skills:
        commands.extend(_skill_command_candidates(skill))

    normalized_to_display = {
        " ".join(_normalize_command_word(w) for w in command.split()): command
        for command in commands
    }
    matches = get_close_matches(normalized, normalized_to_display.keys(), n=1, cutoff=0.55)
    return normalized_to_display[matches[0]] if matches else None

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


def get_git_behind_count(repo_path: str = "~/.cucumber-agent") -> int | None:
    """Return number of commits behind origin/main, or None if unavailable."""
    import subprocess
    try:
        expanded = os.path.expanduser(repo_path)
        # fetch first (quiet)
        subprocess.run(
            ["git", "fetch", "origin"],
            cwd=expanded,
            capture_output=True,
            timeout=10,
        )
        # count behind
        result = subprocess.run(
            ["git", "rev-list", "--count", "--left-right", "@{upstream}...HEAD"],
            cwd=expanded,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            ahead, behind = result.stdout.strip().split()
            return int(behind)
    except Exception:
        pass
    return None


def _load_wiki_key_files(wiki_dir: Path) -> str:
    """
    Load key wiki files (Swarm.md, Autopilot.md, README.md) into a
    single context string so the agent always knows their content.
    """
    key_files = ["Swarm.md", "Autopilot.md", "README.md", "Skills.md", "AgentGuide.md"]
    parts = []
    for fname in key_files:
        fpath = wiki_dir / fname
        if fpath.exists():
            try:
                content = fpath.read_text(encoding="utf-8").strip()
                if content:
                    parts.append(f"## {wiki_dir.name}/{fname}\n\n{content}")
            except Exception:
                pass
    if not parts:
        return ""
    return (
        "## WICHTIG — Agent Wiki (IMMER wissen!)\n\n"
        + "\n\n---\n\n".join(parts)
        + "\n\n[Ende Wiki-Wissen]"
    )


def print_welcome(config: Config) -> None:
    """Print welcome message with personality branding."""
    pers = config.personality
    agent_cfg = config.agent

    # ASCII Cucumber with Glubschaugen
    cucumber_ascii = r"""
           [bold green]_____ [/bold green]
         [bold green]/       \ [/bold green]
        [bold green]|  [white](O)(O)[/white] | [/bold green]
        [bold green]|    [white]<[/white]    | [/bold green]
        [bold green]|  [white]'---'[/white]  | [/bold green]
        [bold green]|         | [/bold green]
        [bold green]|         | [/bold green]
        [bold green]|         | [/bold green]
         [bold green]\_______/ [/bold green]
    """
    console.print(cucumber_ascii)

    # Create a nice header with a border
    header_text = Text.assemble(
        (f"{pers.emoji} ", "bold"),
        (f"{pers.name} ", "bold green"),
        (f"· powered by {agent_cfg.provider}/{agent_cfg.model}", "dim green"),
    )
    console.print(Panel(header_text, border_style="green", expand=False))
    console.print()

    # Capabilities as a row of badges
    badges = []
    if config.preferences.can_search_web:
        badges.append("[reverse green] 🔍 SEARCH [/reverse green]")
    if config.preferences.can_code:
        badges.append("[reverse cyan] 💻 SHELL [/reverse cyan]")
    badges.append("[reverse blue] 🤖 SUBAGENT [/reverse blue]")

    console.print(Columns(badges, padding=(0, 2)))

    # Show active provider and model clearly
    console.print(
        f"\n  [dim]Provider:[/dim] [bold cyan]{agent_cfg.provider}[/bold cyan]  "
        f"[dim]Modell:[/dim] [bold cyan]{agent_cfg.model}[/bold cyan]"
    )

    # Git behind notice
    behind = get_git_behind_count()
    if behind is not None and behind > 0:
        console.print(
            f"\n  [yellow]⚠️  {behind} Commit(s) hinter origin/main — "
            f"[bold]/update[/bold] zum Aktualisieren[/yellow]"
        )
    elif behind is not None and behind == 0:
        console.print(f"\n  [dim]✔  Auf Stand mit origin/main[/dim]")
    # if None: git not available or not a repo — stay silent

    console.print("\n[dim]Tippe [bold]/help[/bold] für Befehle oder einfach loslegen![/dim]")
    console.print()


def print_help() -> None:
    """Print help message."""
    table = Table(show_header=True, header_style="bold green", box=None, padding=(0, 2))
    table.add_column("Befehl", style="bold cyan", no_wrap=True)
    table.add_column("Beschreibung", style="white")

    commands = [
        ("/help", "Diese Hilfe anzeigen"),
        ("/exit", "CucumberAgent beenden"),
        ("/clear", "Gesprächsverlauf löschen (Kontext bleibt erhalten)"),
        ("/config", "Aktuelle Konfiguration anzeigen"),
        ("/model", "Aktuelles Modell anzeigen"),
        ("/update", "Git pull origin/main — Updates einspielen"),
        ("/optimize", "Persönlichkeit basierend auf Namen optimieren"),
        ("/debug", "Debug-Modus ein/ausschalten"),
        ("/memory", "Alle gemerkten Fakten anzeigen"),
        ("/context", "Aktuelle Context-Auslastung anzeigen"),
        ("/autopilot <plan|run|status|report|reset>", "Projekt-Autopilot planen und ausführen"),
        ("/history [N]", "Letzte N Nachrichten anzeigen (Standard: 10)"),
        ("/undo", "Letzte Benutzer+Assistenten-Nachricht entfernen"),
        ("/export", "Session als Markdown-Datei exportieren"),
        ("/remember ...", "Fakt merken, z.B. /remember name: David"),
        ("/forget ...", "Fakt vergessen, z.B. /forget name"),
        ("/skills", "Installierte Skills auflisten"),
        ("/autoapprove", "Tool-Auto-Approve für diese Session ein/ausschalten"),
        ("/compact", "Gesprächsverlauf jetzt manuell komprimieren"),
        ("/pin <text>", "Text dauerhaft in System-Prompt pinnen (überlebt Komprimierung)"),
        ("/unpin <nr>", "Gepinnten Eintrag entfernen (/pin ohne Arg zeigt Liste)"),
        ("/cost", "Token-Verbrauch und geschätzte Kosten dieser Session anzeigen"),
        ("Mehrzeilig", "Zeile mit \\ beenden → nächste Zeile eingeben (beliebig viele)"),
    ]
    for cmd, desc in commands:
        table.add_row(cmd, desc)

    console.print()
    console.print(
        Panel(table, title="[bold green]Befehle[/bold green]", border_style="green", padding=(1, 2))
    )
    console.print()


def print_config(config: Config) -> None:
    """Print configuration."""
    pers = config.personality
    agent = config.agent

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Key", style="dim")
    table.add_column("Value", style="white")

    table.add_row("Provider", f"[cyan]{agent.provider}[/cyan]")
    table.add_row("Modell", f"[cyan]{agent.model}[/cyan]")
    table.add_row("Temperatur", str(agent.temperature))
    table.add_row("Name", f"{pers.emoji} {pers.name}")
    table.add_row("Ton", pers.tone)
    table.add_row("Sprache", pers.language)
    table.add_row("Greeting", pers.greeting or "—")
    table.add_row("Stärken", pers.strengths or "—")

    console.print()
    console.print(
        Panel(
            table,
            title="[bold green]Konfiguration[/bold green]",
            border_style="green",
            padding=(1, 2),
        )
    )
    console.print()


def parse_personality_update(text: str) -> tuple[dict | None, str] | None:
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

    # Backup before overwriting — so a bad AI output can be recovered
    import shutil

    personality_file = config.config_dir / "personality" / "personality.md"
    if personality_file.exists():
        shutil.copy2(personality_file, personality_file.with_suffix(".md.bak"))

    pers.to_markdown(personality_file)
    # Update system prompt in agent config
    config.agent.system_prompt = pers.to_system_prompt()
    config.save()


def _format_http_error(e: Exception) -> str:
    """Return a friendly, actionable message for HTTP provider errors."""
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        hints: dict[int, str] = {
            400: "Ungültige Anfrage — prüfe deine Eingabe oder den Modellnamen.",
            401: "Authentifizierung fehlgeschlagen — API-Key prüfen (`cucumber config`).",
            403: "Zugriff verweigert — API-Key hat keine Berechtigung für dieses Modell.",
            404: "Endpunkt nicht gefunden — Basis-URL oder Modellname prüfen.",
            429: "Zu viele Anfragen — kurz warten, dann erneut versuchen.",
            500: "Server-Fehler beim Provider — bitte später erneut versuchen.",
            502: "Bad Gateway — der Provider ist möglicherweise kurzzeitig nicht erreichbar.",
            503: "Service nicht verfügbar — der Provider ist überlastet oder in Wartung.",
            529: "Provider überlastet (529) — kurz warten und erneut versuchen.",
        }
        hint = hints.get(code, f"HTTP {code} — Details: {e.response.text[:200]}")
        return f"[bold red]Provider-Fehler {code}:[/bold red] {hint}"

    if isinstance(e, httpx.ConnectError | httpx.TimeoutException):
        return "[bold red]Verbindungsfehler:[/bold red] Der Provider ist nicht erreichbar. Internetverbindung und Base-URL prüfen."

    return f"[bold red]Fehler:[/bold red] {e}"


class CliSession:
    """CLI REPL session."""

    def __init__(self, agent: Agent, config: Config):
        self._agent = agent
        self._config = config
        self._session = Session(id="main", model=config.agent.model)
        self._running = False
        self._waiting_for_optimization_response = False
        self._debug_mode = False
        self._pending_tool_calls: list[dict] = []
        self._auto_approve_session: bool = False
        self._smart_retry = config.preferences.smart_retry
        self._retry_count: dict[str, int] = {}
        self._session_tokens: dict[str, int] = {"input": 0, "output": 0, "calls": 0}

        # Memory & persistence
        self._facts = FactsStore(config.memory.facts_file)
        self._logger = SessionLogger(config.memory.log_dir)
        from cucumber_agent.memory import SessionSummary

        self._summary_store = SessionSummary(config.memory.summary_file)

        # Skills & Custom Tools
        self._skill_loader = SkillLoader()
        self._skill_loader.load_all()

        # Import tools
        from cucumber_agent import tools  # noqa: F401

        self._custom_tool_loader = tools.CustomToolLoader()
        self._custom_tool_loader.load_all()

    async def run(self) -> None:
        """Run the REPL."""
        # Populate session metadata once at startup
        workspace = self._config.workspace or Path.cwd()
        ws = WorkspaceDetector.detect(workspace)
        self._session.metadata["workspace"] = ws.to_context_string()
        self._session.metadata["facts_context"] = self._facts.to_context_string()

        # Self-awareness: Tell the agent where its own files are
        config_dir = self._config.config_dir
        wiki_dir = workspace / "wiki"
        self._session.metadata["agent_context"] = (
            f"Agent Home: {config_dir} | "
            f"Personality File: {config_dir}/personality/personality.md | "
            f"Custom Tools: {config_dir}/custom_tools | "
            f"Project Wiki: {wiki_dir}"
        )

        # ── Load key wiki files into context so the agent always knows them ──
        wiki_content = _load_wiki_key_files(wiki_dir)
        if wiki_content:
            self._session.metadata["wiki_knowledge"] = wiki_content

        # Long-term Memory: Load recent conversations from logs + latest session summary
        if self._config.memory.enabled:
            summary = self._summary_store.load()
            if not summary:
                # Fallback to logs if no specific session summary exists
                summary = self._logger.get_recent_summary(days=3, max_entries=10)

            if summary:
                self._session.metadata["summary"] = summary
                console.print("  [dim]🧠 Vergangene Unterhaltungen geladen...[/dim]")

        print_welcome(self._config)

        pers = self._config.personality

        # Build slash-command completer (static + skill commands)
        completer = WordCompleter(_completion_commands(self._skill_loader), sentence=True)

        ptk_style = PtkStyle.from_dict(
            {
                "prompt": "bold ansibrightgreen",
                "auto-suggest": "ansibrightblack",
            }
        )
        history = InMemoryHistory()
        pt_session: PromptSession = PromptSession(
            history=history,
            auto_suggest=AutoSuggestFromHistory(),
            completer=completer,
            complete_while_typing=True,
            style=ptk_style,
        )

        self._running = True
        while self._running:
            try:
                if not self._debug_mode:
                    prompt_text = HTML(
                        f"<b><ansigreen>{pers.emoji} {pers.name}&gt;</ansigreen></b> "
                    )
                else:
                    prompt_text = HTML(f"<b><ansired>🔧 {pers.name} [DEBUG]&gt;</ansired></b> ")

                user_input = await pt_session.prompt_async(prompt_text)

                # Multi-line continuation: trailing \ means "more to come"
                while user_input.endswith("\\"):
                    user_input = user_input[:-1] + "\n"
                    cont = await pt_session.prompt_async(
                        HTML("<b><ansicyan>  ...</ansicyan></b> ")
                    )
                    user_input += cont

                await self._handle_input(user_input)
            except KeyboardInterrupt:
                console.print(
                    "\n  [dim]Strg+C erkannt. Tippe [bold]/exit[/bold] zum Beenden.[/dim]"
                )
            except EOFError:
                if self._config.memory.enabled and self._session.messages:
                    try:
                        exit_summary = await self._agent.summarize_messages(self._session.messages)
                        if exit_summary.strip():
                            existing = self._summary_store.load() or ""
                            combined = (
                                existing.strip() + "\n\n[Neue Sitzung:]\n" + exit_summary.strip()
                                if existing.strip()
                                else exit_summary.strip()
                            )
                            self._summary_store.save(combined)
                    except Exception:
                        pass
                console.print(f"\n[bold green]{pers.emoji}  Tschüss![/bold green]\n")
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
        if self._pending_tool_calls:
            await self._handle_tool_approval(user_input)
            return

        # Regular chat
        console.print()

        # Hot-reload custom tools if needed
        if self._custom_tool_loader.needs_reload():
            self._custom_tool_loader.load_all()

        try:
            offer_optimization = self._agent.needs_optimization(user_input)
            with console.status("  [dim]denkt nach...[/dim]", spinner="dots", spinner_style="dim"):
                response = await self._agent.run_with_tools(self._session, user_input)

            self._track_tokens(response)
            await self._process_agent_response(response, user_input)

            # After first greeting, offer optimization
            if offer_optimization:
                pers = self._config.personality
                console.print(Rule(style="dim cyan"))
                console.print(
                    f"  [bold]{pers.emoji}  Möchtest du, dass ich meine Persönlichkeit optimiere?[/bold]"
                )
                console.print(
                    "  [dim]Ich kann Emoji, Greeting und Stärken basierend auf meinem Namen anpassen.[/dim]"
                )
                console.print(
                    "  [dim]Antworte mit [bold white]ja[/bold white] oder [bold white]nein[/bold white][/dim]"
                )
                console.print(Rule(style="dim cyan"))
                console.print()
                self._waiting_for_optimization_response = True

        except Exception as e:
            logger.error(f"CLI error: {e}", exc_info=True)
            console.print(_format_http_error(e))
            if self._debug_mode:
                import traceback

                console.print(f"[dim red]{traceback.format_exc()}[/dim red]")

    async def _process_agent_response(self, response, user_input: str = "") -> None:
        """Process the agent's response, handling tool calls and text output."""
        if response.tool_calls:
            if response.content and response.content.strip():
                import re

                # Clean up thinking/reasoning blocks
                clean_tool_content = re.sub(
                    r"<(think|thinking|thought)>.*?</\1>",
                    "",
                    response.content,
                    flags=re.DOTALL | re.IGNORECASE,
                ).strip()

                if clean_tool_content:
                    words = clean_tool_content.lower()
                    if not any(
                        w in words for w in ["ich", "i will", "let me", "now", "jetzt", "werde"]
                    ):
                        console.print(f"  [dim]{clean_tool_content}[/dim]")
                    console.print()

            # Auto-execute safe tools, queue the rest for approval
            auto_calls = []
            manual_calls = []
            for tc in response.tool_calls:
                tool_obj = ToolRegistry.get(tc.name)
                if tool_obj and getattr(tool_obj, "auto_approve", False):
                    auto_calls.append(tc)
                else:
                    manual_calls.append(tc)

            # Session-level auto-approve: promote all manual calls to auto
            if self._auto_approve_session:
                auto_calls.extend(manual_calls)
                manual_calls = []

            # Execute auto-approved tools immediately
            for tc in auto_calls:
                console.print(f"  [dim]⚡ {tc.name}...[/dim]")
                auto_result = await ToolRegistry.execute(tc.name, **tc.arguments)
                auto_output = (
                    auto_result.output
                    if auto_result.success
                    else "ERROR: " + (auto_result.error or auto_result.output)
                )
                if len(auto_output) > 3000:
                    auto_output = auto_output[:1500] + "\n...[TRUNCATED]...\n" + auto_output[-1500:]

                self._session.messages.append(
                    SessionMessage(
                        role=SessionRole.TOOL,
                        content=auto_output,
                        name=tc.name,
                        tool_call_id=tc.id,
                    )
                )
                # If remember tool, refresh facts in live session
                if tc.name == "remember":
                    self._facts._facts = self._facts._load()
                    self._session.metadata["facts_context"] = self._facts.to_context_string()
                if auto_result.success and auto_output.strip():
                    console.print(f"  [dim green]✓ {auto_output.strip()[:120]}[/dim green]")

            # If only auto-approve tools, synthesize response
            if not manual_calls:
                if auto_calls:
                    with console.status(
                        "  [dim]denkt nach...[/dim]", spinner="dots", spinner_style="dim"
                    ):
                        follow_up = await self._agent.run_with_tools(self._session, "")
                    self._track_tokens(follow_up)
                    await self._process_agent_response(follow_up)
                return

            # Queue manual tool calls for approval
            self._pending_tool_calls = [
                {"name": tc.name, "arguments": tc.arguments, "id": tc.id} for tc in manual_calls
            ]
            self._print_tool_call(self._pending_tool_calls[0])
            return

        # Regular text response
        if response.content and response.content.strip():
            import re

            # Extract thinking blocks (handles <think>, <thinking>, <thought> case-insensitive)
            thinking_blocks = re.findall(
                r"<(think|thinking|thought)>(.*?)</\1>",
                response.content,
                flags=re.DOTALL | re.IGNORECASE,
            )
            # Clean up the main content
            clean_content = re.sub(
                r"<(think|thinking|thought)>.*?</\1>",
                "",
                response.content,
                flags=re.DOTALL | re.IGNORECASE,
            ).strip()

            # Display thinking blocks if any
            if thinking_blocks:
                for _, block in thinking_blocks:
                    if block.strip():
                        console.print(f"  [dim italic white]💭 {block.strip()}[/dim italic white]")
                console.print()

            if not clean_content:
                return

            pers = self._config.personality

            # Use a Panel for the response to make it look premium
            panel = Panel(
                clean_content,
                title=f"[bold green]{pers.emoji} {pers.name}[/bold green]",
                title_align="left",
                border_style="dim green",
                padding=(1, 2),
            )
            console.print(panel)

            # Show context usage
            current_messages = self._agent._build_messages(self._session)
            total_tokens = self._agent.estimate_tokens(current_messages)
            max_context = self._config.context.max_tokens
            usage_pct = (total_tokens / max_context) * 100

            # Determine color based on usage
            color = "green"
            if usage_pct > 80:
                color = "red"
            elif usage_pct > 50:
                color = "yellow"

            console.print(
                f"  [dim]Context: [{color}]{total_tokens}[/{color}] / {max_context} tokens ({usage_pct:.1f}%)[/dim]\n"
            )

            # Log the exchange (only if we have a user input to pair it with)
            if self._config.memory.enabled and user_input:
                self._logger.log_exchange(user_input, clean_content)
                # Passive learning: detect facts in user message
                from cucumber_agent.memory import detect_learnable_facts

                learnable = detect_learnable_facts(user_input)
                for key, value in learnable:
                    if not self._facts.get(key):
                        self._facts.set(key, value)
                        self._session.metadata["facts_context"] = self._facts.to_context_string()
                        console.print(f"  [dim]🧠 Gemerkt: {key} = {value}[/dim]")
                # Auto-compress if history is getting too long
                await self._maybe_compress_context()

    async def _maybe_compress_context(self) -> None:
        """Compress old messages into a summary if the history is too long."""
        if not self._config.memory.enabled:
            return

        # Trigger one message BEFORE the hard limit to avoid context overflow
        if len(self._session.messages) < self._config.memory.max_session_messages - 1:
            return

        console.print("  [dim]🔄 Komprimiere Gesprächsverlauf...[/dim]")

        # Keep the most recent messages, summarize the rest
        keep_recent = self._config.memory.summarize_keep_recent
        to_summarize = self._session.messages[:-keep_recent]
        remaining = self._session.messages[-keep_recent:]

        # Create summary
        new_summary = await self._agent.summarize_messages(to_summarize)

        # Update session — append to existing summary instead of overwriting
        existing = self._session.metadata.get("summary", "")
        if existing:
            combined = existing.strip() + "\n\n[Neuere Zusammenfassung:]\n" + new_summary.strip()
        else:
            combined = new_summary.strip()
        self._session.metadata["summary"] = combined
        self._session.messages = remaining

        # Persist summary to disk
        self._summary_store.save(combined)
        console.print("  [dim]✓ Verlauf zusammengefasst und gespeichert.[/dim]")

    async def _handle_optimization_response(self, user_input: str) -> None:
        """Handle user's response to optimization offer."""
        self._waiting_for_optimization_response = False

        response = user_input.lower().strip()

        # Check if user declined
        no_patterns = [
            r"^nein\b",
            r"^no\b",
            r"^n\b",
            r"^ne\b",
            r"^überspring\b",
            r"^skip\b",
            r"^nee\b",
        ]
        if any(re.match(p, response) for p in no_patterns):
            console.print("[dim]OK, überspringe Optimierung.[/dim]\n")
            return

        # User wants optimization - check if response contains positive intent
        positive_patterns = [
            r"^ja\b",
            r"^yes\b",
            r"^optimier",
            r"^ok\b",
            r"^okay\b",
            r"^gerne\b",
            r"^yo\b",
        ]
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

        console.print()
        with console.status(
            "  [dim]Analysiere Persönlichkeit...[/dim]", spinner="dots", spinner_style="dim"
        ):
            stream = self._agent.run_stream(optimization_session, optimization_prompt)
            full_response = await stream_print(stream)

        console.print()

        # Parse and apply any personality update from AI response
        result = parse_personality_update(full_response)
        if result:
            update_params, explanation = result
            if update_params:
                apply_personality_update(update_params, self._config)
                console.print(f"\n[dim]{explanation}[/dim]")
                console.print(
                    "\n[green]✅ Personality optimized! Changes saved to personality.md[/green]\n"
                )
                console.print("[dim]Restart: Ctrl+C + cucumber run[/dim]\n")
            else:
                # KEINE_VERBESSERUNG — AI decided current values are already optimal
                console.print(f"\n[dim]{explanation}[/dim]\n")
                console.print("[dim]OK, nothing to improve.[/dim]\n")
        else:
            console.print("\n[dim]OK, nothing to improve.[/dim]\n")

    async def _handle_command(self, user_input: str) -> None:
        """Handle slash commands."""
        # Hot-reload skills if files changed
        if self._skill_loader.needs_reload():
            self._skill_loader.load_all()

        # Check for skill commands first, including aliases and punctuation-tolerant input.
        skill_invocation = _resolve_skill_invocation(user_input, self._skill_loader)
        if skill_invocation:
            skill, args = skill_invocation
            console.print(f"  [dim magenta]⚡ Skill: {skill.name}[/dim magenta]\n")

            with console.status("  [dim]führe aus...[/dim]", spinner="dots", spinner_style="dim"):
                try:
                    result = await SkillRunner.run(skill, args, self._session, self._agent)
                    logger.info(f"Skill executed: {skill.name} | args: '{args}'")
                except Exception as e:
                    logger.error(f"Skill failed: {skill.name} | args: '{args}' | error: {e}")
                    result = f"[red]Fehler bei der Skill-Ausführung: {e}[/red]"

            pers = self._config.personality
            console.print(Rule(f"[dim green]{pers.emoji}[/dim green]", style="dim green"))
            console.print()
            console.print(result)
            console.print()
            return

        parts = user_input.strip().split(None, 1)
        cmd = _normalize_command_word(parts[0]) if parts else ""
        # Extract argument for parametric commands
        arg = user_input.strip()[len(parts[0]) :].strip()

        match cmd:
            case "/help":
                print_help()
            case "/exit" | "/quit":
                pers = self._config.personality
                if self._config.memory.enabled and self._session.messages:
                    try:
                        console.print("  [dim]💾 Speichere Gesprächszusammenfassung...[/dim]")
                        exit_summary = await self._agent.summarize_messages(self._session.messages)
                        if exit_summary.strip():
                            existing = self._summary_store.load() or ""
                            combined = (
                                existing.strip() + "\n\n[Neue Sitzung:]\n" + exit_summary.strip()
                                if existing.strip()
                                else exit_summary.strip()
                            )
                            self._summary_store.save(combined)
                            console.print("  [dim green]✓ Zusammenfassung gespeichert.[/dim green]")
                    except Exception:
                        pass
                console.print(f"[bold green]{pers.emoji}  Tschüss![/bold green]\n")
                self._running = False
            case "/clear":
                meta = dict(self._session.metadata)  # preserve workspace + facts
                self._session = Session(id="main", model=self._config.agent.model)
                self._session.metadata.update(meta)
                console.print("  [dim green]✓ Gesprächsverlauf gelöscht[/dim green]\n")
            case "/config":
                print_config(self._config)
            case "/model":
                cfg = self._config.agent
                console.print(f"  [dim]{cfg.provider}[/dim] / [bold cyan]{cfg.model}[/bold cyan]\n")
            case "/update":
                behind = get_git_behind_count()
                if behind is None:
                    console.print("  [red]Git nicht verfügbar oder kein Repo.[/red]\n")
                elif behind == 0:
                    console.print("  [dim]✔  Bereits auf neuestem Stand (origin/main).[/dim]\n")
                else:
                    console.print(f"  [yellow]⬇ {behind} Commit(s) werden eingepielt...[/yellow]")
                    import subprocess as _subprocess
                    try:
                        res = _subprocess.run(
                            ["git", "pull", "origin", "main"],
                            cwd=os.path.expanduser("~/.cucumber-agent"),
                            capture_output=True,
                            text=True,
                            timeout=60,
                        )
                        if res.returncode == 0:
                            console.print(f"  [green]✔ Aktualisiert! Starte Cucumber neu für die Änderungen.[/green]\n")
                        else:
                            console.print(f"  [red]✘ Git-Fehler: {res.stderr or res.stdout}[/red]\n")
                    except Exception as exc:
                        console.print(f"  [red]✘ Fehler: {exc}[/red]\n")
            case "/debug":
                self._debug_mode = not self._debug_mode
                if self._debug_mode:
                    console.print("  [bold red]🔧 Debug-Modus AN[/bold red]")
                    self._print_debug_info()
                else:
                    console.print("  [dim]Debug-Modus AUS[/dim]\n")
            case "/autoapprove":
                self._auto_approve_session = not self._auto_approve_session
                self._sync_subagent_approve()
                if self._auto_approve_session:
                    console.print(
                        "  [bold green]✓ Auto-Approve AN[/bold green] — alle Tool-Aufrufe (inkl. Sub-Agenten) werden automatisch ausgeführt.\n"
                    )
                else:
                    console.print("  [dim]Auto-Approve AUS — Tool-Aufrufe wieder manuell bestätigen.[/dim]\n")
            case "/compact":
                keep_recent = self._config.memory.summarize_keep_recent
                msgs = self._session.messages
                if len(msgs) <= keep_recent:
                    console.print(
                        f"  [dim]Nicht genug Nachrichten zum Komprimieren ({len(msgs)} ≤ {keep_recent}).[/dim]\n"
                    )
                else:
                    old_count = len(msgs)
                    console.print("  [dim]🔄 Komprimiere...[/dim]")
                    to_summarize = msgs[:-keep_recent]
                    remaining = msgs[-keep_recent:]
                    new_summary = await self._agent.summarize_messages(to_summarize)
                    existing = self._session.metadata.get("summary", "")
                    combined = (
                        existing.strip() + "\n\n[Manuell komprimiert:]\n" + new_summary.strip()
                        if existing.strip()
                        else new_summary.strip()
                    )
                    self._session.metadata["summary"] = combined
                    self._session.messages = remaining
                    self._summary_store.save(combined)
                    console.print(
                        f"  [green]✓ {old_count} → {len(remaining)} Nachrichten "
                        f"({old_count - len(remaining)} komprimiert und gespeichert)[/green]\n"
                    )
            case "/pin":
                if not arg:
                    pins = self._session.metadata.get("pinned_items", [])
                    if not pins:
                        console.print("  [dim]Kein gepinnter Kontext. Verwendung: /pin <text>[/dim]\n")
                    else:
                        console.print()
                        for i, p in enumerate(pins, 1):
                            console.print(f"  [bold cyan]{i}.[/bold cyan] {p}")
                        console.print()
                else:
                    pins = self._session.metadata.get("pinned_items", [])
                    pins.append(arg.strip())
                    self._session.metadata["pinned_items"] = pins
                    self._session.metadata["pinned"] = "\n".join(f"- {p}" for p in pins)
                    console.print(f'  [green]✓ Gepinnt:[/green] „{arg.strip()}"\n')
            case "/unpin":
                pins = self._session.metadata.get("pinned_items", [])
                if not pins:
                    console.print("  [dim]Kein gepinnter Kontext vorhanden.[/dim]\n")
                elif not arg:
                    console.print("  [dim]Verwendung: /unpin <nr>  (Nummern mit /pin anzeigen)[/dim]\n")
                else:
                    try:
                        idx = int(arg) - 1
                        if 0 <= idx < len(pins):
                            removed = pins.pop(idx)
                            self._session.metadata["pinned_items"] = pins
                            self._session.metadata["pinned"] = (
                                "\n".join(f"- {p}" for p in pins) if pins else ""
                            )
                            console.print(f'  [green]✓ Entfernt:[/green] „{removed}"\n')
                        else:
                            console.print(f"  [dim]Index {arg} ungültig. Zeige Pins mit /pin[/dim]\n")
                    except ValueError:
                        console.print("  [dim]Bitte eine Zahl eingeben, z.B. /unpin 1[/dim]\n")
            case "/cost":
                tok = self._session_tokens
                provider = self._config.agent.provider
                # Approximate price per 1M tokens (input, output) in USD
                price_table: dict[str, tuple[float, float]] = {
                    "minimax":    (0.80,  2.40),
                    "openrouter": (1.00,  3.00),
                    "ollama":     (0.00,  0.00),
                    "deepseek":   (0.14,  0.28),
                }
                in_p, out_p = price_table.get(provider, (1.00, 3.00))
                cost_usd = (tok["input"] / 1_000_000 * in_p) + (tok["output"] / 1_000_000 * out_p)

                t = Table(show_header=False, box=None, padding=(0, 2))
                t.add_column("Key",   style="dim")
                t.add_column("Value", style="white")
                t.add_row("Provider",      f"[cyan]{provider}[/cyan]")
                t.add_row("API-Aufrufe",   str(tok["calls"]))
                t.add_row("Input Tokens",  f"[yellow]{tok['input']:,}[/yellow]")
                t.add_row("Output Tokens", f"[yellow]{tok['output']:,}[/yellow]")
                t.add_row("Gesamt",        f"[bold]{tok['input'] + tok['output']:,}[/bold]")
                t.add_row("~Kosten",       f"[green]${cost_usd:.5f} USD[/green]")
                if in_p == 0:
                    t.add_row("",  "[dim]Lokal — kostenlos[/dim]")
                console.print()
                console.print(
                    Panel(t, title="[bold cyan]💰 Token-Kosten[/bold cyan]", border_style="cyan", padding=(0, 1))
                )
                console.print()
            case "/memory":
                facts = self._facts.all()
                if not facts:
                    console.print("  [dim]Keine gemerkten Fakten.[/dim]\n")
                else:
                    table = Table(show_header=False, box=None, padding=(0, 2))
                    table.add_column("Key", style="cyan")
                    table.add_column("Value", style="white")
                    for k, v in facts.items():
                        table.add_row(k, v)
                    console.print()
                    console.print(
                        Panel(
                            table,
                            title="[bold cyan]🧠 Gemerkte Fakten[/bold cyan]",
                            border_style="cyan",
                            padding=(0, 1),
                        )
                    )
                    console.print()
            case "/context":
                current_messages = self._agent._build_messages(self._session)
                total_tokens = self._agent.estimate_tokens(current_messages)
                max_context = self._config.context.max_tokens
                usage_pct = (total_tokens / max_context) * 100

                table = Table(show_header=False, box=None, padding=(0, 2))
                table.add_row("Aktueller Context:", f"[bold]{total_tokens}[/bold] Tokens")
                table.add_row("Maximaler Context:", f"{max_context} Tokens")
                table.add_row("Auslastung:", f"{usage_pct:.1f}%")

                summary_status = (
                    "[green]Aktiv[/green]"
                    if self._session.metadata.get("summary")
                    else "[dim]Inaktiv[/dim]"
                )
                table.add_row("Gesprächs-Summary:", summary_status)
                table.add_row("Nachrichten (Live):", f"{len(self._session.messages)}")

                # Show a small progress bar
                bar_width = 20
                filled = int(usage_pct / (100 / bar_width)) if usage_pct < 100 else bar_width
                bar = "█" * filled + "░" * (bar_width - filled)
                color = "green"
                if usage_pct > 80:
                    color = "red"
                elif usage_pct > 50:
                    color = "yellow"

                console.print(
                    Panel(
                        table,
                        title="[bold cyan]📊 Context-Status[/bold cyan]",
                        border_style="cyan",
                        subtitle=f"[{color}]{bar}[/{color}]",
                    )
                )
                console.print()
            case "/autopilot":
                await self._handle_autopilot_command(arg)
            case "/remember":
                if not arg:
                    console.print("  [dim]Verwendung: /remember key: wert[/dim]\n")
                else:
                    key = self._facts.add_from_text(arg)
                    # Update session metadata so it's active immediately
                    self._session.metadata["facts_context"] = self._facts.to_context_string()
                    console.print(f"  [green]✓ Gemerkt als „{key}“[/green]\n")
            case "/forget":
                if not arg:
                    console.print("  [dim]Verwendung: /forget schlüssel[/dim]\n")
                elif self._facts.delete(arg):
                    self._session.metadata["facts_context"] = self._facts.to_context_string()
                    console.print(f"  [green]✓ „{arg}“ vergessen[/green]\n")
                else:
                    console.print(f"  [dim]Kein Fakt namens „{arg}“ gefunden.[/dim]\n")
            case "/tools":
                tools_list = ToolRegistry.list_tools()
                if not tools_list:
                    console.print("  [dim]Keine Tools registriert.[/dim]\n")
                else:
                    table = Table(
                        show_header=True, header_style="bold yellow", box=None, padding=(0, 2)
                    )
                    table.add_column("Tool", style="bold cyan", no_wrap=True)
                    table.add_column("Auto", style="dim", no_wrap=True)
                    table.add_column("Beschreibung", style="white")
                    for tname in sorted(tools_list):
                        tool_obj = ToolRegistry.get(tname)
                        auto = (
                            "[green]✓[/green]"
                            if getattr(tool_obj, "auto_approve", False)
                            else "[dim]—[/dim]"
                        )
                        desc = (
                            (tool_obj.description[:60] + "…")
                            if tool_obj and len(tool_obj.description) > 60
                            else (tool_obj.description if tool_obj else "")
                        )
                        table.add_row(tname, auto, desc)
                    console.print()
                    console.print(
                        Panel(
                            table,
                            title="[bold yellow]🔧 Tools[/bold yellow]",
                            border_style="yellow",
                            padding=(0, 1),
                        )
                    )
                    console.print()
            case "/skills":
                skills = self._skill_loader.skills
                if not skills:
                    console.print(
                        "  [dim]Keine Skills installiert. Lege .yaml-Dateien in ~/.cucumber/skills/ ab.[/dim]\n"
                    )
                else:
                    table = Table(
                        show_header=True, header_style="bold magenta", box=None, padding=(0, 2)
                    )
                    table.add_column("Befehl", style="bold cyan", no_wrap=True)
                    table.add_column("Args", style="dim", no_wrap=True)
                    table.add_column("Aliase", style="dim")
                    table.add_column("Beschreibung", style="white")
                    for s in skills:
                        aliases = ", ".join(getattr(s, "aliases", None) or [])
                        table.add_row(s.command, s.args_hint, aliases, s.description)
                    console.print()
                    console.print(
                        Panel(
                            table,
                            title="[bold magenta]⚡ Skills[/bold magenta]",
                            border_style="magenta",
                            padding=(0, 1),
                        )
                    )
                    console.print()
            case "/history":
                # Parse optional N argument (default 10)
                try:
                    n = int(arg) if arg else 10
                except ValueError:
                    n = 10
                n = max(1, n)
                messages = self._session.messages
                if not messages:
                    console.print("  [dim]Keine Nachrichten in dieser Session.[/dim]\n")
                else:
                    recent = messages[-n:]
                    console.print()
                    console.print(
                        Panel(
                            f"[dim]Letzte {len(recent)} von {len(messages)} Nachrichten[/dim]",
                            title="[bold blue]📜 Verlauf[/bold blue]",
                            border_style="blue",
                            padding=(0, 1),
                        )
                    )
                    for msg in recent:
                        role_val = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
                        content_text = (
                            msg.content if isinstance(msg.content, str) else str(msg.content)
                        )
                        # Truncate long messages for display
                        if len(content_text) > 300:
                            content_text = content_text[:300] + " [dim]…[/dim]"
                        role_colors = {
                            "user": "bold green",
                            "assistant": "bold cyan",
                            "system": "bold yellow",
                            "tool": "bold magenta",
                        }
                        color = role_colors.get(role_val, "white")
                        console.print(f"  [{color}]{role_val.upper()}:[/{color}] {content_text}")
                    console.print()
            case "/undo":
                # Remove last user + assistant message pair
                msgs = self._session.messages
                if not msgs:
                    console.print("  [dim]Keine Nachrichten zum Rückgängigmachen.[/dim]\n")
                else:
                    # Find and remove the last assistant message
                    removed = 0
                    if msgs and msgs[-1].role == SessionRole.ASSISTANT:
                        msgs.pop()
                        removed += 1
                    # Then remove the last user message
                    if msgs and msgs[-1].role == SessionRole.USER:
                        msgs.pop()
                        removed += 1
                    if removed:
                        console.print(
                            f"  [green]✓ {removed} Nachricht(en) entfernt.[/green] "
                            f"[dim]({len(msgs)} verbleibend)[/dim]\n"
                        )
                    else:
                        console.print("  [dim]Nichts zum Rückgängigmachen gefunden.[/dim]\n")
            case "/export":
                import datetime

                msgs = self._session.messages
                if not msgs:
                    console.print("  [dim]Keine Nachrichten zum Exportieren.[/dim]\n")
                else:
                    cfg = self._config.agent
                    pers = self._config.personality
                    now = datetime.datetime.now()
                    date_str = now.strftime("%Y-%m-%d_%H-%M-%S")
                    filename = f"cucumber-session-{date_str}.md"
                    downloads = Path.home() / "Downloads"
                    downloads.mkdir(parents=True, exist_ok=True)
                    export_path = downloads / filename

                    lines: list[str] = [
                        f"# CucumberAgent Session — {now.strftime('%Y-%m-%d %H:%M')}",
                        "",
                        f"**Agent:** {pers.emoji} {pers.name}  ",
                        f"**Provider:** {cfg.provider} / {cfg.model}  ",
                        f"**Nachrichten:** {len(msgs)}",
                        "",
                        "---",
                        "",
                    ]
                    for msg in msgs:
                        role_val = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
                        content_text = (
                            msg.content if isinstance(msg.content, str) else str(msg.content)
                        )
                        role_header = {
                            "user": "## Benutzer",
                            "assistant": f"## {pers.emoji} {pers.name}",
                            "system": "## System",
                            "tool": "## Tool",
                        }.get(role_val, f"## {role_val.capitalize()}")
                        lines.append(role_header)
                        lines.append("")
                        lines.append(content_text)
                        lines.append("")
                        lines.append("---")
                        lines.append("")

                    export_path.write_text("\n".join(lines), encoding="utf-8")
                    console.print(
                        f"  [green]✓ Session exportiert:[/green] [bold]{export_path}[/bold]\n"
                    )
            case _:
                suggestion = _command_suggestion(user_input, self._skill_loader, STATIC_SLASH_COMMANDS)
                if suggestion:
                    console.print(
                        "  [dim]Unbekannter Befehl: "
                        f"[bold]{cmd}[/bold]. Meintest du [bold cyan]{suggestion}[/bold cyan]?[/dim]\n"
                    )
                else:
                    console.print(
                        f"  [dim]Unbekannter Befehl: [bold]{cmd}[/bold]. Tippe /help für Hilfe.[/dim]\n"
                    )

    async def _handle_autopilot_command(self, args: str) -> None:
        """Handle the native /autopilot command family."""
        workspace = Path(self._config.workspace or Path.cwd()).expanduser().resolve()
        store = AutopilotStore(workspace, self._config.config_dir / "autopilot")

        try:
            parsed = parse_autopilot_args(args)
        except Exception as exc:
            console.print(f"  [red]Autopilot: Ungueltige Argumente: {exc}[/red]\n")
            return

        if parsed.action == "plan":
            if not parsed.goal:
                console.print(
                    "  [dim]Verwendung: /autopilot plan <ziel>, z.B. "
                    "/autopilot plan verbessere das Arcade Projekt[/dim]\n"
                )
                return
            state = create_plan(parsed.goal, workspace)
            store.save(state)
            self._print_autopilot_tasks(state, title="Autopilot Plan")
            console.print(f"  [dim]State: {store.path}[/dim]\n")
            return

        if parsed.action == "status":
            console.print()
            console.print(
                Panel(
                    status_text(store.load()),
                    title="[bold cyan]Agent Autopilot[/bold cyan]",
                    border_style="cyan",
                    padding=(0, 1),
                )
            )
            console.print()
            return

        if parsed.action == "report":
            console.print()
            console.print(
                Panel(
                    report_text(store.load()),
                    title="[bold cyan]Autopilot Report[/bold cyan]",
                    border_style="cyan",
                    padding=(0, 1),
                )
            )
            console.print()
            return

        if parsed.action == "reset":
            state = store.load()
            if state is None:
                console.print("  [dim]Autopilot: kein State fuer diesen Workspace vorhanden.[/dim]\n")
                return
            if not parsed.yes:
                console.print(
                    "  [yellow]Autopilot Reset abgebrochen.[/yellow] "
                    "Nutze /autopilot reset --yes zum Bestaetigen.\n"
                )
                return
            store.reset()
            console.print("  [green]✓ Autopilot State geloescht.[/green]\n")
            return

        if parsed.action == "run":
            state = store.load()
            if state is None:
                console.print(
                    "  [dim]Autopilot: kein Plan vorhanden. Nutze zuerst "
                    "/autopilot plan <ziel>.[/dim]\n"
                )
                return
            with console.status(
                "  [dim cyan]Autopilot arbeitet...[/dim cyan]",
                spinner="dots",
                spinner_style="dim cyan",
            ):
                try:
                    state = await run_plan(
                        state,
                        parallel=parsed.parallel,
                        timeout=parsed.timeout,
                        dry_run=parsed.dry_run,
                    )
                except Exception as exc:
                    console.print(f"  [red]Autopilot Fehler: {exc}[/red]\n")
                    return
            store.save(state)
            self._print_autopilot_tasks(
                state,
                title="Autopilot Dry Run" if parsed.dry_run else "Autopilot Run",
            )
            return

        console.print("  [dim]Verwendung: /autopilot <plan|run|status|report|reset>[/dim]\n")

    def _print_autopilot_tasks(self, state: AutopilotState, *, title: str) -> None:
        table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 2))
        table.add_column("Task", style="bold cyan", no_wrap=True)
        table.add_column("Status", style="white", no_wrap=True)
        table.add_column("Rolle", style="dim", no_wrap=True)
        table.add_column("Beschreibung", style="white")

        status_style = {
            "pending": "dim",
            "running": "yellow",
            "done": "green",
            "failed": "red",
        }
        for task in state.tasks:
            style = status_style.get(task.status, "white")
            detail = task.error or task.result or task.detail
            if len(detail) > 90:
                detail = detail[:87] + "..."
            table.add_row(task.id, f"[{style}]{task.status}[/{style}]", task.agent_role, detail)

        console.print()
        console.print(
            Panel(
                table,
                title=f"[bold cyan]{title}: {state.goal}[/bold cyan]",
                border_style="cyan",
                padding=(0, 1),
            )
        )
        console.print()

    async def _handle_tool_approval(self, user_input: str) -> None:
        """Handle user's response to a tool call."""
        if not self._pending_tool_calls:
            console.print("[dim]No pending tool call.[/dim]\n")
            return

        tool_call = self._pending_tool_calls[0]
        choice = user_input.strip()
        tool_name = tool_call.get("name", "unknown")
        args = tool_call.get("arguments", {})
        command = args.get("command", "")

        if choice == "1":
            # Execute
            self._pending_tool_calls.pop(0)
            console.print(f"\n[dim]⚡ Executing {tool_name}...[/dim]\n")
            result = await ToolRegistry.execute(tool_name, **args)

            # Log tool execution
            logger.info(
                f"Tool executed: {tool_name} | success: {result.success} | args: {str(args)[:100]}"
            )
            if not result.success:
                logger.warning(f"Tool failed: {tool_name} | error: {result.error}")

            from cucumber_agent.session import Message, Role

            # Then add the actual tool result
            output_text = (
                result.output if result.success else "ERROR: " + (result.error or result.output)
            )
            if len(output_text) > 3000:
                output_text = output_text[:1500] + "\n... [TRUNCATED] ...\n" + output_text[-1500:]

            tool_result_msg = Message(
                role=Role.TOOL,
                content=output_text,
                name=tool_name,
                tool_call_id=tool_call.get("id", ""),
            )
            self._session.messages.append(tool_result_msg)

            if result.success:
                stripped = output_text.strip()
                if stripped:
                    lang = "text"
                    if command:
                        if any(x in command for x in ["python", ".py", "pip"]):
                            lang = "python"
                        elif any(x in command for x in [".json", "jq"]):
                            lang = "json"
                        elif any(
                            x in command for x in ["ls", "find", "cat", "grep", "git", "echo"]
                        ):
                            lang = "bash"
                    console.print(
                        Panel(
                            Syntax(stripped[:4000], lang, theme="monokai", word_wrap=True),
                            title="[dim green]✓ Output[/dim green]",
                            border_style="dim green",
                            padding=(0, 1),
                        )
                    )
                    console.print()
                else:
                    console.print("[green]✓ Done[/green]\n")
            else:
                error = result.error or result.output
                console.print(
                    Panel(
                        error,
                        title="[bold red]✗ Error[/bold red]",
                        border_style="red",
                    )
                )
                console.print()

                # Check if we should auto-retry (only for shell commands)
                if command:
                    from cucumber_agent.smart_retry import should_auto_retry

                    decision = should_auto_retry(command, error, self._smart_retry)
                    retry_key = f"{tool_name}:{command}"

                    if decision.should_retry and self._retry_count.get(retry_key, 0) < 2:
                        self._retry_count[retry_key] = self._retry_count.get(retry_key, 0) + 1

                        if decision.alternatives:
                            new_cmd = decision.alternatives[0]
                            console.print("[yellow]↻ Auto-retrying with alternative...[/yellow]\n")
                            args["command"] = new_cmd
                        else:
                            console.print("[yellow]↻ Auto-retrying same command...[/yellow]\n")

                        await self._execute_auto_retry(
                            tool_name, args, command, self._retry_count[retry_key]
                        )
                        return

            # If more tool calls queued, show next one
            if self._pending_tool_calls:
                self._print_tool_call(self._pending_tool_calls[0])
                return

            # Let AI respond or continue reasoning based on tool result
            with console.status("  [dim]denkt nach...[/dim]", spinner="dots", spinner_style="dim"):
                response = await self._agent.run_with_tools(self._session, "")
            self._track_tokens(response)
            await self._process_agent_response(response)

        elif choice == "2":
            # Cancel this tool call
            tool_call = self._pending_tool_calls.pop(0)
            console.print("[dim]Tool call cancelled.[/dim]\n")

            # Add a "cancelled" result to satisfy API requirements
            from cucumber_agent.session import Message, Role

            self._session.messages.append(
                Message(
                    role=Role.TOOL,
                    content="Cancelled by user.",
                    name=tool_name,
                    tool_call_id=tool_call.get("id", ""),
                )
            )

            # Show next if available
            if self._pending_tool_calls:
                self._print_tool_call(self._pending_tool_calls[0])
                return

            # Continue if no more pending
            with console.status("  [dim]denkt nach...[/dim]", spinner="dots", spinner_style="dim"):
                response = await self._agent.run_with_tools(self._session, "")
            self._track_tokens(response)
            await self._process_agent_response(response)

        elif choice == "3":
            # Edit the command (pre-flight — before agent continues)
            if not command:
                console.print("  [dim]Bearbeiten nur für Befehle möglich.[/dim]\n")
                self._print_tool_call(self._pending_tool_calls[0])
                return

            from prompt_toolkit import prompt as ptk_prompt
            from prompt_toolkit.formatted_text import HTML

            new_cmd = await asyncio.to_thread(
                ptk_prompt,
                HTML("  <b><ansiyellow>Befehl &gt;</ansiyellow></b> "),
                default=command,
            )
            if new_cmd.strip():
                self._pending_tool_calls[0]["arguments"]["command"] = new_cmd.strip()
                console.print()
                self._print_tool_call(self._pending_tool_calls[0])
                return  # Wait for next choice
            else:
                console.print("  [dim]Befehl unverändert.[/dim]\n")
                self._print_tool_call(self._pending_tool_calls[0])
                return

        elif choice in ("4", "a", "all"):
            # Enable session-wide auto-approve (incl. sub-agents), then execute current
            self._auto_approve_session = True
            self._sync_subagent_approve()
            console.print("  [dim green]✓ Auto-Approve AN für diese Session — alle weiteren Tools (inkl. Sub-Agenten) werden automatisch ausgeführt.[/dim green]\n")
            await self._handle_tool_approval("1")

        else:
            self._pending_tool_calls.clear()
            console.print("[dim]Ungültige Eingabe. Alle ausstehenden Tool-Aufrufe abgebrochen.[/dim]\n")

    def _print_tool_call(self, tool_call: dict) -> None:
        """Display a tool call with approval options."""
        tool_name = tool_call.get("name", "unknown")
        args = tool_call.get("arguments", {})
        reason = args.get("reason", "")

        # Build a generic display of arguments
        arg_lines = []
        for key, value in args.items():
            if key == "reason":
                continue
            display_val = str(value)
            if len(display_val) > 120:
                display_val = display_val[:120] + "…"
            arg_lines.append(f"[bold]{key}:[/bold] {display_val}")

        panel_content = f"[bold]Tool:[/bold] [cyan]{tool_name}[/cyan]\n" + "\n".join(arg_lines)
        if reason:
            panel_content += f"\n[bold]Reason:[/bold] [dim]{reason}[/dim]"

        # Show queue info if multiple calls pending
        queue_info = ""
        if len(self._pending_tool_calls) > 1:
            queue_info = f" ({len(self._pending_tool_calls)} queued)"

        auto_badge = " [dim green][AUTO][/dim green]" if self._auto_approve_session else ""
        console.print(
            Panel(
                panel_content,
                title=f"⚡ [bold yellow]Tool Approval Required[/bold yellow]{queue_info}{auto_badge}",
                border_style="yellow",
                subtitle="[dim][bold yellow]1[/bold yellow] ausführen · [bold red]2[/bold red] abbrechen · [bold green]4[/bold green] alle akzeptieren[/dim]",
            )
        )

        # Nicer menu display
        menu_text = Text.assemble(
            ("  [1] ", "bold yellow"),
            ("Ausführen   ", "default"),
            ("  [2] ", "bold red"),
            ("Abbrechen   ", "default"),
        )
        if args.get("command"):
            menu_text.append("  [3] ", style="bold cyan")
            menu_text.append("Bearbeiten   ", style="default")
        menu_text.append("  [4] ", style="bold green")
        menu_text.append("Alle akzeptieren", style="default")

        console.print(menu_text)
        console.print()

    async def _execute_auto_retry(
        self,
        tool_name: str,
        args: dict,
        original_cmd: str,
        retry_num: int = 1,
    ) -> None:
        """Execute an auto-retry without requiring user approval."""
        from cucumber_agent.session import Message, Role
        from cucumber_agent.smart_retry import should_auto_retry

        command = args.get("command", "")
        console.print(f"[yellow]↻ Auto-retry ({retry_num}/2):[/yellow] {command}\n")

        result = await ToolRegistry.execute(tool_name, **args)

        # Add to session
        assistant_msg = Message(
            role=Role.ASSISTANT, content=f"[AUTO-RETRY {retry_num}] Ich probiere: {command}"
        )
        self._session.messages.append(assistant_msg)

        tool_result_msg = Message(
            role=Role.USER,
            content=f"[TOOL_RESULT] {tool_name}: {result.output if result.success else 'ERROR: ' + (result.error or result.output)}",
        )
        self._session.messages.append(tool_result_msg)

        if result.success:
            console.print("[green]✓[/green]\n")
            resp = await self._agent.synthesize(self._session)
            if resp.strip():
                console.print(resp)
                console.print()
        else:
            error = result.error or result.output
            decision = should_auto_retry(command, error, self._smart_retry)

            if decision.should_retry and retry_num < 2:
                # Try alternative or retry
                if decision.alternatives:
                    new_cmd = decision.alternatives[0]
                    console.print(f"[dim]Trying alternative:[/dim] {new_cmd}\n")
                    args["command"] = new_cmd
                    await self._execute_auto_retry(tool_name, args, original_cmd, retry_num + 1)
                else:
                    # Same command, just retry
                    await self._execute_auto_retry(tool_name, args, original_cmd, retry_num + 1)
            else:
                # Give up
                console.print("[red]✗ Command failed after auto-retry.[/red]\n")
                resp = await self._agent.synthesize(
                    self._session,
                    "Der Befehl ist nach mehreren Versuchen fehlgeschlagen. Erkläre dem Benutzer die Situation.",
                )
                if resp.strip():
                    console.print(resp)
                    console.print()

    def _sync_subagent_approve(self) -> None:
        """Propagate _auto_approve_session to the sub-agent tool's module flag."""
        try:
            from cucumber_agent.tools.agent import set_subagent_auto_approve
            set_subagent_auto_approve(self._auto_approve_session)
        except Exception:
            pass

    def _track_tokens(self, response) -> None:
        """Accumulate token counts from a ModelResponse."""
        self._session_tokens["input"] += response.input_tokens or 0
        self._session_tokens["output"] += response.output_tokens or 0
        self._session_tokens["calls"] += 1

    def _print_debug_info(self) -> None:
        """Print debug information."""
        pers = self._config.personality
        ctx = self._config.context
        agent = self._config.agent

        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("Key", style="dim")
        table.add_column("Value", style="white")
        table.add_row("provider", agent.provider)
        table.add_row("model", agent.model)
        table.add_row("temperature", str(agent.temperature))
        table.add_row("max_tokens", str(ctx.max_tokens))
        table.add_row("remember", str(ctx.remember_last))
        table.add_row("messages", str(len(self._session.messages)))
        table.add_row("name", f"{pers.emoji} {pers.name}")
        table.add_row("tone", pers.tone)
        table.add_row("language", pers.language)

        console.print()
        console.print(
            Panel(
                table,
                title="[bold red]🔧 Debug Info[/bold red]",
                border_style="red",
                padding=(0, 1),
            )
        )
        console.print()


async def run_cli() -> None:
    """Run the CLI session."""
    config = Config.load()

    # Initialize logging from config
    import logging

    log_level = getattr(logging, config.logging.level.upper(), logging.INFO)
    setup_logging(
        log_dir=config.logging.log_dir,
        level=log_level,
        verbose=config.logging.verbose,
    )

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
        console.print(
            "[bold red]Error:[/bold red] Could not find installer. Run from project directory."
        )
        sys.exit(1)


def run_update() -> None:
    """Update CucumberAgent from GitHub."""
    import os
    import subprocess

    console.print("[bold]🔄 Updating CucumberAgent...[/bold]\n")

    install_dir = Path.home() / ".cucumber-agent"
    update_script = install_dir / "installer" / "update.sh"

    if not install_dir.exists():
        console.print("[red]ERROR:[/red] Installation not found at ~/.cucumber-agent")
        console.print("Run the installer first: curl ... | sh")
        sys.exit(1)

    # If the dedicated update script exists, use it
    if update_script.exists():
        os.chmod(update_script, 0o755)
        result = subprocess.run([str(update_script)], cwd=install_dir)
        sys.exit(result.returncode)

    # Fallback legacy logic if script not found
    try:
        console.print("→ Pulling latest from GitHub...")
        result = subprocess.run(
            ["git", "pull", "origin", "main"],
            cwd=install_dir,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            if "Already up to date" in result.stdout:
                console.print("[green]✅ Already up to date![/green]\n")
                return

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
    """Show configuration or run a sub-command (e.g. 'validate')."""
    sub = sys.argv[2] if len(sys.argv) > 2 else None
    config = Config.load()

    if sub == "validate":
        issues = config.validate()
        if not issues:
            console.print("[bold green]✓ Config looks good — no problems found.[/bold green]")
        else:
            console.print(f"[bold yellow]Found {len(issues)} issue(s):[/bold yellow]\n")
            for i, msg in enumerate(issues, 1):
                console.print(f"  [yellow]{i}.[/yellow] {msg}")
        return

    print_config(config)


def run_tui() -> None:
    """Launch the prompt_toolkit + Rich TUI."""
    import logging

    from cucumber_agent.agent import Agent
    from cucumber_agent.tui import CucumberTUI

    config = Config.load()

    log_level = getattr(logging, config.logging.level.upper(), logging.INFO)
    setup_logging(
        log_dir=config.logging.log_dir,
        level=log_level,
        verbose=config.logging.verbose,
    )

    agent = Agent.from_config(config)
    tui = CucumberTUI(agent, config)
    tui.run()


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
        elif cmd == "tui":
            run_tui()
            return
        elif cmd in ("--help", "-h"):
            console.print("[bold]CucumberAgent CLI[/bold]\n")
            console.print("Commands:")
            console.print("  [cyan]cucumber run[/cyan]     Start chat session (legacy REPL)")
            console.print("  [cyan]cucumber tui[/cyan]     Start chat session (new Textual TUI)")
            console.print("  [cyan]cucumber init[/cyan]    Run setup wizard")
            console.print("  [cyan]cucumber config[/cyan]           Show configuration")
            console.print("  [cyan]cucumber config validate[/cyan]  Validate configuration")
            console.print("  [cyan]cucumber --help[/cyan]  Show this help")
            return

    try:
        asyncio.run(run_cli())
    except KeyboardInterrupt:
        pass
