"""Sub-agent tool for delegating complex tasks."""

from __future__ import annotations

import asyncio
import re
import time

from prompt_toolkit import prompt as ptk_prompt
from prompt_toolkit.formatted_text import HTML
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from cucumber_agent.config import Config
from cucumber_agent.session import Message, Role, Session
from cucumber_agent.tools.base import BaseTool, ToolResult
from cucumber_agent.tools.registry import ToolRegistry

console = Console()

# Max characters of tool output to keep in session context (prevents blowup)
MAX_TOOL_OUTPUT_CHARS = 3000
MAX_PROGRESS_NOTE_CHARS = 220
MAX_RESULT_PREVIEW_CHARS = 700

# Session-level auto-approve flag — set to True by the main CLI when
# _auto_approve_session is enabled so sub-agents skip approval prompts too.
_subagent_auto_approve: bool = False


def set_subagent_auto_approve(value: bool) -> None:
    global _subagent_auto_approve
    _subagent_auto_approve = value


def _truncate_output(text: str, max_chars: int = MAX_TOOL_OUTPUT_CHARS) -> str:
    """Truncate long tool output to prevent context window overflow."""
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    return text[:half] + f"\n\n... [TRUNCATED {len(text) - max_chars} chars] ...\n\n" + text[-half:]


def _format_args_display(args: dict) -> str:
    """Format tool arguments for display in a readable way."""
    lines = []
    for key, value in args.items():
        if key == "reason":
            continue  # shown separately
        display_val = str(value)
        if len(display_val) > 120:
            display_val = display_val[:120] + "…"
        lines.append(f"  [cyan]{key}:[/cyan] {display_val}")
    return "\n".join(lines)


def _compact_text(text: str, max_chars: int) -> str:
    """Collapse whitespace and shorten a string for terminal status display."""
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 1].rstrip() + "…"


def _public_progress_note(text: str) -> str:
    """Extract a short public progress note from assistant content."""
    if not text or not text.strip():
        return ""

    for line in text.splitlines():
        clean = line.strip().strip("-*• ")
        if clean and not clean.startswith("```"):
            return _compact_text(clean, MAX_PROGRESS_NOTE_CHARS)
    return ""


def _tool_stage_summary(tool_calls: list) -> str:
    """Summarise the visible action for a step from its tool calls."""
    if not tool_calls:
        return "Ergebnis formulieren"

    names = ", ".join(tc.name for tc in tool_calls[:3])
    if len(tool_calls) > 3:
        names += f" +{len(tool_calls) - 3}"

    first_args = tool_calls[0].arguments or {}
    reason = first_args.get("reason") or first_args.get("query") or first_args.get("path") or ""
    if not reason and tool_calls[0].name == "shell":
        reason = first_args.get("command", "")

    if reason:
        return f"{names}: {_compact_text(str(reason), 120)}"
    return f"{names} vorbereiten"


def _result_preview(result: ToolResult) -> str:
    """Return a short result preview suitable for display."""
    text = result.output if result.success else result.error or result.output
    if not text or not text.strip():
        return ""
    return _compact_text(text, MAX_RESULT_PREVIEW_CHARS)


class AgentTool(BaseTool):
    """Delegate a complex task to a sub-agent."""

    name = "agent"
    description = (
        "Delegiert eine komplexe, mehrstufige Aufgabe an einen autonomen Sub-Agenten. "
        "Verwende dieses Tool immer dann, wenn eine Aufgabe viele Teilschritte erfordert "
        "(z.B. 'Recherchiere X und schreibe dann Y', 'Analysiere das Projekt und erstelle ein Refactoring-Konzept'). "
        "Dies hält den Haupt-Chat übersichtlich und ermöglicht spezialisierte Bearbeitung."
    )
    parameters = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "Die genaue Aufgabenbeschreibung für den Sub-Agenten.",
            }
        },
        "required": ["task"],
    }

    async def execute(self, task: str) -> ToolResult:
        """Execute the sub-agent loop."""
        start_time = time.monotonic()

        console.print()
        console.print(
            Panel(
                f"[bold magenta]🤖 Sub-Agent gestartet[/bold magenta]\n\n"
                f"[italic]Aufgabe:[/italic] {task}",
                border_style="magenta",
                padding=(1, 2),
            )
        )

        config = Config.load()
        from cucumber_agent.agent import Agent

        agent = Agent.from_config(config)
        session = Session(id="subagent", model=config.agent.model)

        # Give the sub-agent context about its role
        system_prompt = config.agent.system_prompt or ""
        subagent_prompt = (
            f"{system_prompt}\n\n"
            "WICHTIG: Du bist ein SUB-AGENT. Dir wurde eine komplexe Aufgabe übertragen. "
            "Nutze deine Tools (shell, search), um die Aufgabe Schritt für Schritt zu lösen. "
            "BENUTZE NIEMALS das 'agent' Tool — du bist selbst der Sub-Agent! "
            "Wenn du ein Tool nutzt, schreibe vorher genau eine kurze öffentliche Fortschrittsnotiz "
            "(ein Satz, was du als Nächstes prüfst oder baust; keine privaten Gedankengänge). "
            "Setze im Tool-Argument 'reason' einen konkreten, nutzerverständlichen Zweck. "
            "Wenn du fertig bist, fasse das Ergebnis zusammen und beende deine Arbeit "
            "ohne weitere Tool-Aufrufe. Mache keine Konversation, liefere nur Ergebnisse."
        )
        agent._agent_config.system_prompt = subagent_prompt

        max_steps = 15
        step = 0
        current_input = task
        final_response = ""
        aborted = False

        while step < max_steps:
            step += 1

            try:
                with console.status(
                    f"  [dim magenta]Sub-Agent plant Schritt {step}...[/dim magenta]",
                    spinner="dots",
                    spinner_style="dim magenta",
                ):
                    response = await agent.run_with_tools(session, current_input)
            except Exception as e:
                elapsed = time.monotonic() - start_time
                console.print(
                    Panel(
                        f"[bold red]Sub-Agent Fehler:[/bold red] {e}",
                        border_style="red",
                    )
                )
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Sub-agent crashed after {elapsed:.1f}s: {e}",
                )

            progress_bar = "█" * step + "░" * (max_steps - step)
            stage = _tool_stage_summary(response.tool_calls or [])
            console.print(
                f"  [bold magenta]Schritt {step}[/bold magenta] "
                f"[dim magenta](max. {max_steps})[/dim magenta]  "
                f"[magenta]{progress_bar}[/magenta]\n"
                f"  [magenta]→[/magenta] {escape(stage)}"
            )

            # No tool calls → agent is done
            if not response.tool_calls:
                final_response = response.content or ""
                if final_response.strip():
                    console.print()
                    console.print(
                        Panel(
                            final_response,
                            title="[magenta]Sub-Agent Ergebnis[/magenta]",
                            border_style="magenta",
                            padding=(1, 2),
                        )
                    )
                break

            # Show a public progress note, not private chain-of-thought.
            progress_note = _public_progress_note(response.content)
            if progress_note:
                console.print(f"  [dim magenta]Notiz:[/dim magenta] {escape(progress_note)}")

            # Handle each tool call
            for tc in response.tool_calls:
                tc_name = tc.name
                tc_args = tc.arguments

                # Safety: prevent recursive agent calls (depth check)
                if tc_name == "agent":
                    console.print(
                        "  [yellow]⚠ Sub-Agent versuchte sich selbst aufzurufen "
                        "— übersprungen.[/yellow]"
                    )
                    session.messages.append(
                        Message(
                            role=Role.USER,
                            content=(
                                "[TOOL_RESULT] agent: FEHLER — Rekursive Sub-Agent-Aufrufe "
                                "sind nicht erlaubt. Nutze shell oder search direkt."
                            ),
                        )
                    )
                    continue

                # Safety: block shell commands that try to invoke cucumber itself
                if tc_name == "shell":
                    shell_cmd = tc_args.get("command", "")
                    if shell_cmd and any(
                        cmd in shell_cmd for cmd in ("cucumber run", "cucumber", "hermes")
                    ):
                        console.print(
                            "  [yellow]⚠ Shell-Befehl blockiert — würde mich selbst aufrufen.[/yellow]"
                        )
                        session.messages.append(
                            Message(
                                role=Role.USER,
                                content=(
                                    "[TOOL_RESULT] shell: FEHLER — Befehl blockiert, "
                                    "da er den Agenten selbst aufrufen würde."
                                ),
                            )
                        )
                        continue

                reason = tc_args.get("reason", "")
                command = tc_args.get("command", "")

                # Build a nice tool call display
                tool_info = _format_args_display(tc_args)
                panel_content = f"[bold]Tool:[/bold] [cyan]{tc_name}[/cyan]\n{tool_info}"
                if reason:
                    panel_content += f"\n[bold]Grund:[/bold] [dim]{reason}[/dim]"

                console.print(
                    Panel(
                        panel_content,
                        title="[yellow]⚡ Sub-Agent Tool-Aufruf[/yellow]",
                        border_style="yellow",
                        padding=(0, 1),
                    )
                )

                # Ask user for approval — capture current values to avoid closure bug
                choice = await self._ask_approval()

                if choice == "1":
                    await self._execute_tool(tc_name, tc_args, session)
                elif choice == "3" and "command" in tc_args:
                    await self._edit_and_execute(tc_name, tc_args, command, session)
                elif choice == "4":
                    # Auto-approve all remaining tool calls for this sub-agent run
                    set_subagent_auto_approve(True)
                    console.print(
                        "  [dim green]✓ Auto-Approve AN — alle weiteren Tool-Aufrufe "
                        "dieses Sub-Agenten werden automatisch ausgeführt.[/dim green]"
                    )
                    await self._execute_tool(tc_name, tc_args, session)
                elif choice == "5":
                    # Abort entire sub-agent
                    console.print("  [red]Sub-Agent abgebrochen.[/red]")
                    session.messages.append(
                        Message(
                            role=Role.USER,
                            content=f"[TOOL_RESULT] {tc_name} wurde vom Benutzer abgebrochen. Die gesamte Aufgabe wird beendet.",
                        )
                    )
                    aborted = True
                    break
                else:
                    # Skip this tool (choice == "2" or anything else)
                    console.print("  [dim]Übersprungen.[/dim]")
                    session.messages.append(
                        Message(
                            role=Role.USER,
                            content=f"[TOOL_RESULT] {tc_name} wurde vom Benutzer übersprungen.",
                        )
                    )

            if aborted:
                final_response = "Sub-Agent wurde vom Benutzer abgebrochen."
                break

            # Prompt the agent to continue
            current_input = (
                "Analysiere die bisherigen Tool-Ergebnisse. "
                "Fahre fort, falls nötig, oder schließe die Aufgabe mit einer Zusammenfassung ab."
            )

        if step >= max_steps and not final_response:
            console.print("  [bold yellow]⚠ Schritt-Limit erreicht.[/bold yellow]")
            # Ask the agent for a final summary
            try:
                summary_response = await agent.synthesize(
                    session, "Fasse zusammen was bisher erreicht wurde."
                )
                final_response = summary_response
            except Exception:
                final_response = "Sub-Agent hat das Schritt-Limit erreicht, ohne eine Zusammenfassung zu liefern."

        elapsed = time.monotonic() - start_time

        # Reset sub-agent auto-approve after run (main session flag re-sets it if needed)
        set_subagent_auto_approve(False)

        # Summary table
        summary = Table.grid(padding=(0, 2))
        summary.add_row("[bold]Schritte:[/bold]", f"{step} genutzt (Limit: {max_steps})")
        summary.add_row("[bold]Dauer:[/bold]", f"{elapsed:.1f}s")
        summary.add_row(
            "[bold]Status:[/bold]",
            "[green]✓ Abgeschlossen[/green]" if not aborted else "[red]✗ Abgebrochen[/red]",
        )

        console.print()
        console.print(
            Panel(
                summary,
                title="[bold magenta]🏁 Sub-Agent beendet[/bold magenta]",
                border_style="magenta",
                padding=(0, 1),
            )
        )

        return ToolResult(
            success=not aborted,
            output=(f"Sub-Agent Ergebnis ({step} Schritte, {elapsed:.1f}s):\n\n{final_response}"),
        )

    # ── Helper methods ──────────────────────────────────────────────────

    async def _ask_approval(self) -> str:
        """Prompt user for tool approval. Returns the choice string."""
        if _subagent_auto_approve:
            console.print("  [dim green]⚡ Auto-approve[/dim green]")
            return "1"
        console.print(
            "  [bold]Aktion:[/bold]  "
            "[1] Ausführen  [2] Überspringen  [3] Bearbeiten  "
            "[bold green][4] Alle akzeptieren[/bold green]  [red][5] Abbrechen[/red]"
        )
        choice = await asyncio.to_thread(
            ptk_prompt, HTML("  <b><ansiyellow>Wahl &gt;</ansiyellow></b> ")
        )
        return choice.strip()

    async def _execute_tool(self, name: str, args: dict, session: Session) -> ToolResult:
        """Execute a tool and record result in session."""
        console.print(f"  [dim]⚡ Führe [cyan]{name}[/cyan] aus...[/dim]")
        result = await ToolRegistry.execute(name, **args)

        session.messages.append(
            Message(
                role=Role.ASSISTANT,
                content=f"Tool {name} ausgeführt mit: {args}",
            )
        )

        if result.success:
            console.print("  [green]✓ Erfolg[/green]")
            preview = _result_preview(result)
            if preview:
                console.print(f"  [dim]Ausgabe:[/dim] {escape(preview)}")
            truncated = _truncate_output(result.output)
            session.messages.append(
                Message(
                    role=Role.USER,
                    content=f"[TOOL_RESULT] {name}:\n{truncated}",
                )
            )
        else:
            error_msg = result.error or result.output
            preview = _result_preview(result) or error_msg[:200]
            console.print(f"  [red]✗ Fehler:[/red] {escape(preview)}")
            session.messages.append(
                Message(
                    role=Role.USER,
                    content=f"[TOOL_RESULT] {name} ERROR: {error_msg}",
                )
            )
        return result

    async def _edit_and_execute(
        self, name: str, args: dict, original_cmd: str, session: Session
    ) -> ToolResult:
        """Let user edit a command, then execute."""
        console.print(f"  [dim]Aktuell:[/dim] {original_cmd}")
        new_cmd = await asyncio.to_thread(
            ptk_prompt,
            HTML("  <b><ansiyellow>Neuer Befehl &gt;</ansiyellow></b> "),
            default=original_cmd,
        )
        if new_cmd.strip():
            args["command"] = new_cmd.strip()
            return await self._execute_tool(name, args, session)
        else:
            console.print("  [dim]Leere Eingabe — übersprungen.[/dim]")
            session.messages.append(
                Message(
                    role=Role.USER,
                    content=f"[TOOL_RESULT] {name} wurde vom Benutzer übersprungen.",
                )
            )
            return ToolResult(success=False, output="", error="User cancelled edit")


# Register the tool
ToolRegistry.register(AgentTool())
