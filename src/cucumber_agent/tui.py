"""
CucumberAgent Textual TUI — Full rewrite of the CLI interface.
"""

from __future__ import annotations

import asyncio
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.css.query import NoMatches
from textual.widgets import Input, Static
from textual.widgets._rich_log import RichLog

if TYPE_CHECKING:
    from cucumber_agent.agent import Agent
    from cucumber_agent.config import Config


# ─── Colors ────────────────────────────────────────────────────────────────────

# CSS (hex): use in CSS strings or Style objects
GREEN_HEX   = "#4ade80"
DKGREEN_HEX = "#166534"
HBG_HEX     = "#0f172a"
BG_HEX      = "#0b0e14"
IBG_HEX     = "#111827"
BORDER_HEX  = "#1e3a2f"
DIM_HEX     = "#64748b"

# Rich markup: use in [tag] markup strings — Rich only supports named colors
GREEN  = "green"
DIM    = "dim"


# ─── Message Data ─────────────────────────────────────────────────────────────

@dataclass
class ChatMessageData:
    role: str
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    tool_name: str | None = None
    tool_args: dict | None = None
    tool_id: str | None = None


# ─── App ───────────────────────────────────────────────────────────────────────

class CucumberTUI(App):

    CSS = f"""
    CucumberTUI {{
        background: {BG_HEX};
        color: #e2e8f0;
    }}

    #header {{
        height: 2;
        background: {HBG_HEX};
        dock: top;
    }}

    #chat-scroll {{
        background: {BG_HEX};
        dock: top;
    }}

    #input-area {{
        height: 3;
        background: {IBG_HEX};
        dock: bottom;
    }}
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=True),
        Binding("ctrl+l", "clear_chat", "Clear", show=False),
        Binding("ctrl+k", "show_help", "Help", show=False),
    ]

    def __init__(self, agent: "Agent", config: "Config", **kwargs):
        super().__init__(**kwargs)
        self.agent = agent
        self.config = config
        self.messages: list[ChatMessageData] = []
        self._skill_loader = None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def on_mount(self):
        self.title = f"CucumberAgent — {self.config.agent.model}"
        self.sub_title = f"{self.config.agent.provider} · {self.config.personality.name}"
        # Enable markup on RichLog
        self.query_one("#chat-log", RichLog).markup = True
        self._init_agent_session()
        self._print_welcome()

    def compose(self) -> ComposeResult:
        yield Container(Static(id="header"), id="header-container")
        yield VerticalScroll(RichLog(id="chat-log"), id="chat-scroll")
        yield Horizontal(
            Input(placeholder="Nachricht eingeben...", id="user-input"),
            id="input-area",
        )

    def _init_agent_session(self):
        """Initialize agent session, memory, and skills."""
        from cucumber_agent.memory import FactsStore, SessionSummary
        from cucumber_agent.session import Session
        from cucumber_agent.workspace import WorkspaceDetector
        from cucumber_agent import tools as tools_module

        self._agent_session = Session(id="tui", model=self.config.agent.model)

        ws = WorkspaceDetector.detect(self.config.workspace)
        self._agent_session.metadata["workspace"] = ws.to_context_string()

        self._facts = FactsStore(self.config.memory.facts_file)
        self._agent_session.metadata["facts_context"] = self._facts.to_context_string()

        config_dir = self.config.config_dir
        wiki_dir = self.config.workspace / "wiki"
        self._agent_session.metadata["agent_context"] = (
            f"Agent Home: {config_dir} | "
            f"Personality File: {config_dir}/personality/personality.md | "
            f"Custom Tools: {config_dir}/custom_tools | "
            f"Project Wiki: {wiki_dir}"
        )

        if self.config.memory.enabled:
            summary_store = SessionSummary(self.config.memory.summary_file)
            summary = summary_store.load()
            if not summary:
                from cucumber_agent.session_logger import SessionLogger
                logger = SessionLogger(self.config.memory.log_dir)
                summary = logger.get_recent_summary(days=3, max_entries=10)
            if summary:
                self._agent_session.metadata["summary"] = summary

        from cucumber_agent.skills import SkillLoader
        self._skill_loader = SkillLoader()
        self._skill_loader.load_all()

        self._custom_tool_loader = tools_module.CustomToolLoader()
        self._custom_tool_loader.load_all()

    def _print_welcome(self):
        pers = self.config.personality
        header = self.query_one("#header", Static)
        header.update(
            f"[bold][{GREEN}]{pers.emoji} {pers.name}[/{GREEN}][/bold]"
            f"  [dim]·[/dim]  [cyan]{self.config.agent.provider}[/cyan]/[cyan]{self.config.agent.model}[/cyan]"
            f"  [dim]·[/dim]  [dim]Ctrl+L Clear  Ctrl+K Help  Ctrl+C Quit[/dim]"
        )
        self.add_message(
            "system",
            f"[bold][{GREEN}]{pers.emoji} {pers.name}[/{GREEN}][/bold] "
            f"[dim]— Chat startklar. Sag was du brauchst![/dim]",
        )

    # ── Message Management ──────────────────────────────────────────────────

    def add_message(
        self,
        role: str,
        content: str,
        tool_name: str | None = None,
        tool_args: dict | None = None,
        tool_id: str | None = None,
        timestamp: datetime | None = None,
    ):
        msg = ChatMessageData(
            role=role,
            content=content,
            timestamp=timestamp or datetime.now(),
            tool_name=tool_name,
            tool_args=tool_args,
            tool_id=tool_id,
        )
        self.messages.append(msg)
        self._write_message(msg)
        self._scroll_to_bottom()

    def _write_message(self, msg: ChatMessageData):
        chat_log = self.query_one("#chat-log", RichLog)
        line = self._format_message(msg)
        chat_log.write(line)

    def _clear_chat_log(self):
        self.query_one("#chat-log", RichLog).clear()

    def _format_message(self, msg: ChatMessageData) -> str:
        ts = msg.timestamp.strftime("%H:%M")

        if msg.role == "user":
            # User content: escape any [brackets] to prevent markup injection
            content = self._esc_markup(msg.content)
            return f"[{DIM}]{ts}[/{DIM}]  [{GREEN}]{content}[/{GREEN}]\n\n"

        elif msg.role == "assistant":
            # Assistant content: no escaping (it's from the model, Rich handles it)
            content = msg.content
            return f"[          {content}  [{DIM}]{ts}[/{DIM}]\n\n"

        elif msg.role == "tool":
            name = msg.tool_name or "tool"
            args_s = ", ".join(
                f"{k}={str(v)[:60]}" for k, v in (msg.tool_args or {}).items() if k != "reason"
            )
            args_d = f"  [dim]([{DIM}][yellow]{args_s}[/{DIM}][yellow][dim])[/{DIM}]" if args_s else ""
            result = self._esc_markup(msg.content[:200]) if msg.content else "[no output]"
            return (
                f"  [{DIM}][yellow]⚡ {name}[/{DIM}][yellow]{args_d}[/{DIM}]\n"
                f"    [{DIM}]{result}[/{DIM}]...\n\n"
            )

        elif msg.role == "error":
            content = self._esc_markup(msg.content)
            return f"[red]✗[/{red}] {content}  [{DIM}]{ts}[/{DIM}]\n\n"

        else:  # system
            # System content: these are app-generated markup strings, no escaping needed
            return f"{msg.content}  [{DIM}]{ts}[/{DIM}]\n\n"

    def _esc_markup(self, text: str) -> str:
        """Escape text so it's treated as literal (no markup processing)."""
        if not text:
            return ""
        # Replace [ with [[ (Rich escape) — but only if not already an escape
        # We use [[ to represent a literal [
        result = ""
        i = 0
        while i < len(text):
            c = text[i]
            if c == "[":
                # Check if this looks like a Rich tag: [colorname/] or [bold] etc.
                # Simple heuristic: if followed by alphanumeric before ]
                if i + 1 < len(text) and text[i+1].isalpha():
                    # Might be a tag — escape the [
                    result += "[["
                    i += 1
                else:
                    result += "[["
                    i += 1
            else:
                result += c
                i += 1
        return result

    def _scroll_to_bottom(self):
        try:
            self.query_one("#chat-scroll", VerticalScroll).scroll_end(animate=False)
        except NoMatches:
            pass

    def _focus_input(self):
        try:
            self.query_one("#user-input", Input).focus()
        except NoMatches:
            pass

    # ── Input ───────────────────────────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted):
        user_text = event.value.strip()
        if not user_text:
            return
        event.input.value = ""
        if user_text.startswith("/"):
            self._handle_command(user_text)
        else:
            asyncio.create_task(self._run_chat(user_text))

    def _handle_command(self, cmd: str):
        parts = cmd.strip().split(maxsplit=1)
        command = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if command in ("/exit", "/quit", "/q"):
            self.exit()
        elif command in ("/clear", "/cls"):
            self.messages.clear()
            self._clear_chat_log()
            self.add_message("system", "[dim]Chat geleert.[/dim]")
        elif command in ("/help", "/h", "/?"):
            self._show_help()
        elif command == "/config":
            cfg = self.config.agent
            self.add_message("system",
                f"[cyan]Provider:[/cyan] {cfg.provider}\n"
                f"[cyan]Model:[/cyan] {cfg.model}\n"
                f"[cyan]Temperature:[/cyan] {cfg.temperature}"
            )
        elif command == "/memory":
            facts = self._facts.all()
            if facts:
                lines = "\n".join(f"[cyan]{k}[/cyan]: {v}" for k, v in facts.items())
                self.add_message("system", lines)
            else:
                self.add_message("system", "[dim]Keine Fakten gespeichert.[/dim]")
        elif command == "/skills":
            if self._skill_loader and self._skill_loader.skills:
                lines = "\n".join(
                    f"[cyan]{s.command}[/cyan]: {s.description[:60]}"
                    for s in self._skill_loader.skills
                )
                self.add_message("system", lines)
            else:
                self.add_message("system", "[dim]Keine Skills installiert.[/dim]")
        elif command == "/context":
            msgs = self.agent._build_messages(self._agent_session)
            tokens = self.agent.estimate_tokens(msgs)
            max_ctx = self.config.context.max_tokens
            pct = (tokens / max_ctx) * 100
            color = "red" if pct > 80 else "yellow" if pct > 50 else "green"
            self.add_message("system",
                f"[cyan]Nachrichten:[/cyan] {len(self._agent_session.messages)}\n"
                f"[cyan]Tokens:[/cyan] [{color}]{tokens}[/{color}] / {max_ctx} ({pct:.1f}%)"
            )
        else:
            self.add_message("system",
                f"[red]Unbekannter Befehl:[/red] {command}\n"
                "[dim]/help /exit /clear /config /memory /skills /context[/dim]"
            )

    def _show_help(self):
        lines = [
            "[bold]CucumberAgent Commands[/bold]",
            "[cyan]/help[/cyan]     Diese Hilfe",
            "[cyan]/exit[/cyan]     Beenden",
            "[cyan]/clear[/cyan]    Chat leeren",
            "[cyan]/config[/cyan]   Zeige Config",
            "[cyan]/memory[/cyan]    Fakten anzeigen",
            "[cyan]/skills[/cyan]    Verfügbare Skills",
            "[cyan]/context[/cyan]   Context-Status",
            "",
            "[dim]Alles andere = Chat mit dem Agenten[/dim]",
        ]
        self.add_message("system", "\n".join(lines))

    # ── Agent Chat ───────────────────────────────────────────────────────────

    async def _run_chat(self, user_input: str):
        from cucumber_agent.session import Message, Role
        from cucumber_agent.tools import ToolRegistry
        import re

        self.add_message("user", user_input)

        try:
            response = await self.agent.run_with_tools(self._agent_session, user_input)

            if response.content and response.content.strip():
                clean = re.sub(
                    r'<(?:think|thinking|thought)>(.*?)</(?:think|thinking|thought)>',
                    '', response.content, flags=re.DOTALL | re.IGNORECASE
                ).strip()
                if clean:
                    thinking = re.findall(
                        r'<(?:think|thinking|thought)>(.*?)</(?:think|thinking|thought)>',
                        response.content, flags=re.DOTALL | re.IGNORECASE
                    )
                    for block in thinking:
                        if block.strip():
                            self.add_message("assistant", f"[dim italic]💭 {block.strip()}[/dim italic]")
                    self.add_message("assistant", clean)

            if response.tool_calls:
                for tc in response.tool_calls:
                    self.add_message("tool", "Executing...", tool_name=tc.name, tool_args=tc.arguments, tool_id=tc.id)
                    try:
                        result = await ToolRegistry.execute(tc.name, **tc.arguments)
                        output = result.output if result.success else f"ERROR: {result.error or result.output}"
                    except Exception as e:
                        output = f"EXCEPTION: {e}"

                    self._agent_session.messages.append(Message(
                        role=Role.TOOL, content=output, name=tc.name, tool_call_id=tc.id
                    ))
                    self.add_message("assistant", f"[green]✓[/green] {tc.name}\n[dim]{output[:500]}[/dim]")

            current_msgs = self.agent._build_messages(self._agent_session)
            total_tokens = self.agent.estimate_tokens(current_msgs)
            max_ctx = self.config.context.max_tokens
            usage_pct = (total_tokens / max_ctx) * 100
            color = "red" if usage_pct > 80 else "yellow" if usage_pct > 50 else "green"
            self.add_message("system", f"[dim]Context: [{color}]{total_tokens}[/{color}] / {max_ctx} tokens ({usage_pct:.1f}%)[/dim]")

            if self.config.memory.enabled:
                await self._maybe_compress()

        except Exception as e:
            import traceback
            self.add_message("error", f"Fehler: {e}\n[dim]{traceback.format_exc()[:200]}[/dim]")
        finally:
            self._focus_input()

    async def _maybe_compress(self):
        max_msgs = self.config.memory.max_session_messages
        if len(self._agent_session.messages) < max_msgs:
            return
        keep = self.config.memory.summarize_keep_recent
        to_sum = self._agent_session.messages[:-keep]
        remaining = self._agent_session.messages[-keep:]
        new_summary = await self.agent.summarize_messages(to_sum)
        self._agent_session.metadata["summary"] = new_summary
        self._agent_session.messages = remaining
        from cucumber_agent.memory import SessionSummary
        SessionSummary(self.config.memory.summary_file).save(new_summary)
        self.add_message("system", "[dim]✓ Kontext komprimiert.[/dim]")

    # ── Actions ─────────────────────────────────────────────────────────────

    def action_quit(self):
        self.exit()

    def action_clear_chat(self):
        self.messages.clear()
        self._clear_chat_log()
        self.add_message("system", "[dim]Chat geleert.[/dim]")

    def action_show_help(self):
        self._show_help()
