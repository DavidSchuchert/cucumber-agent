"""
CucumberAgent Textual TUI — Full rewrite of the CLI interface.

Layout:
┌─────────────────────────────────────────┐
│ HEADER: Name · Provider/Model · Status  │
├─────────────────────────────────────────┤
│  CHAT LOG (scrollable, bubble-style)    │
│    - User messages (green, left)        │
│    - Assistant messages (blue, right)   │
│    - Tool calls (yellow, indented)     │
│    - Timestamps (dim)                   │
├─────────────────────────────────────────┤
│ INPUT: > [prompt input]                 │
└─────────────────────────────────────────┘
"""

from __future__ import annotations

import asyncio
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, AsyncIterator

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.css.query import NoMatches
from textual.message import Message as TuiMessage
from textual.reactive import reactive
from textual.widgets import Button, Input, Static

if TYPE_CHECKING:
    from cucumber_agent.agent import Agent
    from cucumber_agent.config import Config
    from cucumber_agent.session import Message as AgentMessage


# ─── Colors ────────────────────────────────────────────────────────────────────

CUCUMBER_GREEN = "#4ade80"
CUCUMBER_DARK = "#166534"
HEADER_BG = "#0f172a"
SURFACE = "#0b0e14"
SURFACE_ALT = "#111827"
BORDER = "#1e293b"
TEXT_DIM = "#64748b"
TEXT_MUTED = "#475569"
USER_BG = "#14532d"
ASSISTANT_BG = "#1e3a5f"
TOOL_BG = "#292524"
TOOL_BORDER = "#78716c"
ERROR_BG = "#7f1d1d"
TIMESTAMP_COLOR = "#475569"
INPUT_BG = "#0f172a"


# ─── Message Data ─────────────────────────────────────────────────────────────

@dataclass
class ChatMessageData:
    role: str       # "user" | "assistant" | "tool" | "system" | "error"
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    tool_name: str | None = None
    tool_args: dict | None = None
    tool_id: str | None = None


# ─── Main App ─────────────────────────────────────────────────────────────────

class CucumberTUI(App):
    """The CucumberAgent Textual TUI."""

    CSS = f"""
    CucumberTUI {{
        background: {SURFACE};
        color: #e2e8f0;
    }}

    #header {{
        height: 3;
        background: {HEADER_BG};
        border: solid {BORDER};
        border-bottom: thick {CUCUMBER_GREEN};
        padding: 0 2;
        dock: top;
    }}

    #chat-scroll {{
        background: {SURFACE};
        overflow-y: auto;
        scrollbar-size: 1 1;
    }}

    #chat-log {{
        padding: 1 2;
        height: 100%;
    }}

    #input-area {{
        height: 3;
        background: {INPUT_BG};
        border-top: solid {BORDER};
        dock: bottom;
        padding: 0 2;
    }}

    #user-input {{
        background: {SURFACE};
        border: solid {BORDER};
        border-title: "{CUCUMBER_GREEN} >";
        border-title-style: bold;
        color: #e2e8f0;
        padding: 0 1;
    }}

    .timestamp {{
        width: 5;
        align: center middle;
        color: {TIMESTAMP_COLOR};
        padding: 0 1;
    }}

    .user-row, .assistant-row, .tool-row, .error-row, .system-row {{
        height: auto;
        margin-bottom: 1;
    }}

    .user-content {{
        background: {USER_BG};
        color: #bbf7d0;
        border-left: thick {CUCUMBER_GREEN};
        padding: 0 2;
        width: auto;
        max-width: 80%;
        height: auto;
    }}

    .assistant-content {{
        background: {ASSISTANT_BG};
        color: #e2e8f0;
        border-left: thick {CUCUMBER_DARK};
        padding: 0 2;
        width: auto;
        max-width: 80%;
        height: auto;
    }}

    .tool-row {{
        layout: horizontal;
    }}

    .tool-content {{
        background: {TOOL_BG};
        border: solid {TOOL_BORDER};
        color: #d6d3d1;
        padding: 0 2;
        width: auto;
        max-width: 85%;
        height: auto;
    }}

    .error-content {{
        background: {ERROR_BG};
        color: #fecaca;
        border-left: thick #ef4444;
        padding: 0 2;
        width: auto;
        max-width: 85%;
    }}

    .system-content {{
        color: {TEXT_DIM};
        text-style: italic;
    }}
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=True),
        Binding("ctrl+l", "clear_chat", "Clear", show=False),
        Binding("ctrl+k", "show_help", "Help", show=False),
        Binding("escape", "quit", "", show=False),
    ]

    def __init__(self, agent: "Agent", config: "Config", **kwargs):
        super().__init__(**kwargs)
        self.agent = agent
        self.config = config
        self.messages: list[ChatMessageData] = []
        self._thinking = False
        self._skill_loader = None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def on_mount(self):
        self.title = f"CucumberAgent — {self.config.agent.model}"
        self.sub_title = f"{self.config.agent.provider} · {self.config.personality.name}"
        self._print_header()
        self._print_welcome()
        self._focus_input()
        self._init_agent_session()

    def compose(self) -> ComposeResult:
        yield Container(Static(id="header"))
        yield VerticalScroll(Static(id="chat-log"), id="chat-scroll")
        yield Horizontal(
            Input(placeholder="Nachricht eingeben...", id="user-input"),
            id="input-area",
        )

    def _init_agent_session(self):
        """Initialize agent session, memory, and skills (once at startup)."""
        from cucumber_agent.memory import FactsStore, SessionSummary
        from cucumber_agent.session import Session
        from cucumber_agent.workspace import WorkspaceDetector
        from cucumber_agent.tools import CustomToolLoader

        self._agent_session = Session(id="tui", model=self.config.agent.model)

        # Workspace
        ws = WorkspaceDetector.detect(self.config.workspace)
        self._agent_session.metadata["workspace"] = ws.to_context_string()

        # Memory
        self._facts = FactsStore(self.config.memory.facts_file)
        self._agent_session.metadata["facts_context"] = self._facts.to_context_string()

        # Agent self-awareness
        config_dir = self.config.config_dir
        wiki_dir = self.config.workspace / "wiki"
        self._agent_session.metadata["agent_context"] = (
            f"Agent Home: {config_dir} | "
            f"Personality File: {config_dir}/personality/personality.md | "
            f"Custom Tools: {config_dir}/custom_tools | "
            f"Project Wiki: {wiki_dir}"
        )

        # Long-term memory
        if self.config.memory.enabled:
            summary_store = SessionSummary(self.config.memory.summary_file)
            summary = summary_store.load()
            if not summary:
                from cucumber_agent.session_logger import SessionLogger
                logger = SessionLogger(self.config.memory.log_dir)
                summary = logger.get_recent_summary(days=3, max_entries=10)
            if summary:
                self._agent_session.metadata["summary"] = summary

        # Skills
        from cucumber_agent.skills import SkillLoader
        self._skill_loader = SkillLoader()
        self._skill_loader.load_all()

        # Custom tools
        from cucumber_agent import tools as tools_module
        self._custom_tool_loader = tools_module.CustomToolLoader()
        self._custom_tool_loader.load_all()

    def _print_header(self):
        header = self.query_one("#header", Static)
        pers = self.config.personality
        agent = self.config.agent
        header.update(
            f"[bold green]{pers.emoji} {pers.name}[/bold green]"
            f"  [dim]·[/dim]  [cyan]{agent.provider}[/cyan]/[cyan]{agent.model}[/cyan]"
            f"  [dim]·[/dim]  [dim]Ctrl+L Clear  Ctrl+K Help  Esc Quit[/dim]"
        )

    def _print_welcome(self):
        pers = self.config.personality
        self.add_message(
            role="system",
            content=(
                f"[bold green]{pers.emoji} {pers.name}[/bold green] "
                f"[dim]— Chat startklar. Sag was du brauchst![/dim]"
            ),
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
        self._render()
        self._scroll_to_bottom()

    def _render(self):
        chat_log = self.query_one("#chat-log", Static)
        lines = [self._format_message(m) for m in self.messages]
        chat_log.update("\n".join(lines))

    def _format_message(self, msg: ChatMessageData) -> str:
        ts = msg.timestamp.strftime("%H:%M")
        content = self._markup(msg.content)

        if msg.role == "user":
            return (
                f"[dim]{ts}[/dim]  "
                f"[green]{content}[/green]\n"
            )
        elif msg.role == "assistant":
            return (
                f"        {content}  [dim]{ts}[/dim]\n"
            )
        elif msg.role == "tool":
            name = msg.tool_name or "tool"
            args_s = ", ".join(
                f"{k}={str(v)[:60]}" for k, v in (msg.tool_args or {}).items() if k != "reason"
            )
            args_d = f" [dim]([/dim][yellow]{args_s}[/yellow][dim])[/dim]" if args_s else ""
            result_preview = content[:300] if content else "[no output]"
            return (
                f"  [yellow]⚡ {name}[/yellow]{args_d}  [dim]{ts}[/dim]\n"
                f"    [dim]{result_preview}...[/dim]\n"
            )
        elif msg.role == "error":
            return f"[red]✗[/red] {content}  [dim]{ts}[/dim]\n"
        else:
            return f"[dim]{content}[/dim]  {ts}\n"

    def _markup(self, text: str) -> str:
        """Apply basic markup to text content."""
        if not text:
            return ""
        # Protect literal [[ and ]]
        text = text.replace("[[", "\x00L\x00").replace("]]", "\x00R\x00")
        # Escape brackets for Rich
        text = text.replace("[", "[[")
        text = text.replace("\x00L\x00", "[[")
        text = text.replace("\x00R\x00", "]]")
        # Bold
        text = re.sub(r'\*\*(.+?)\*\*', r'[bold]\1[/bold]', text)
        # Italic
        text = re.sub(r'\*(.+?)\*', r'[italic]\1[/italic]', text)
        # Inline code
        text = re.sub(r'`(.+?)`', r'[yellow]\1[/yellow]', text)
        return text

    def _scroll_to_bottom(self):
        try:
            scroll = self.query_one("#chat-scroll", VerticalScroll)
            scroll.scroll_end(animate=False)
        except NoMatches:
            pass

    def _focus_input(self):
        try:
            inp = self.query_one("#user-input", Input)
            inp.focus()
        except NoMatches:
            pass

    # ── Input ────────────────────────────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted):
        if self._thinking:
            return
        user_text = event.value.strip()
        if not user_text:
            return
        if user_text.startswith("/"):
            self._handle_command(user_text)
        else:
            asyncio.create_task(self._run_chat(user_text))

    def _handle_command(self, cmd: str):
        """Handle slash commands locally (no agent call)."""
        parts = cmd.strip().split(maxsplit=1)
        command = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if command in ("/exit", "/quit", "/q"):
            self.exit()
        elif command in ("/clear", "/cls"):
            self.messages.clear()
            self._render()
            self.add_message("system", "Chat geleert.")
        elif command in ("/help", "/h", "/?"):
            self._show_help()
        elif command == "/config":
            cfg = self.config.agent
            self.add_message("system",
                f"[cyan]Provider:[/cyan] {cfg.provider}\n"
                f"[cyan]Model:[/cyan] {cfg.model}\n"
                f"[cyan]Temperature:[/cyan] {cfg.temperature}\n"
                f"[cyan]Max Tokens:[/cyan] {cfg.max_tokens}"
            )
        elif command == "/memory":
            facts = self._facts.all()
            if facts:
                lines = "\n".join(f"[cyan]{k}[/cyan]: {v}" for k, v in facts.items())
                self.add_message("system", lines)
            else:
                self.add_message("system", "Keine Fakten gespeichert.")
        elif command == "/skills":
            if self._skill_loader and self._skill_loader.skills:
                lines = "\n".join(
                    f"[cyan]{s.command}[/cyan]: {s.description[:60]}"
                    for s in self._skill_loader.skills
                )
                self.add_message("system", lines)
            else:
                self.add_message("system", "Keine Skills installiert.")
        elif command == "/context":
            from cucumber_agent.agent import Agent
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
            "[dim]Ctrl+L Clear  Ctrl+K Help  Esc Quit[/dim]",
        ]
        self.add_message("system", "\n".join(lines))

    # ── Agent Chat ───────────────────────────────────────────────────────────

    async def _run_chat(self, user_input: str):
        """Run a full agent turn with tool execution."""
        from cucumber_agent.session import Message, Role
        from cucumber_agent.tools import ToolRegistry
        import re

        self._thinking = True
        self.add_message("user", user_input)

        try:
            response = await self.agent.run_with_tools(self._agent_session, user_input)

            # Display text content (without thinking blocks)
            if response.content and response.content.strip():
                clean = re.sub(
                    r'<(think|thinking|thought)>(.*?)</\1>',
                    '', response.content, flags=re.DOTALL | re.IGNORECASE
                ).strip()
                if clean:
                    # Show any thinking blocks separately
                    thinking = re.findall(
                        r'<(?:think|thinking|thought)>(.*?)</(?:think|thinking|thought)>',
                        response.content, flags=re.DOTALL | re.IGNORECASE
                    )
                    for block in thinking:
                        if block.strip():
                            self.add_message("assistant", f"[dim italic]💭 {block.strip()}[/dim italic]")
                    self.add_message("assistant", clean)

            # Handle tool calls
            if response.tool_calls:
                for tc in response.tool_calls:
                    self.add_message(
                        "tool",
                        "Executing...",
                        tool_name=tc.name,
                        tool_args=tc.arguments,
                        tool_id=tc.id,
                    )

                    # Execute tool
                    try:
                        result = await ToolRegistry.execute(tc.name, **tc.arguments)
                        if result.success:
                            output = result.output or "(no output)"
                        else:
                            output = f"ERROR: {result.error or result.output}"
                    except Exception as e:
                        output = f"EXCEPTION: {e}"

                    # Append tool result to session (as Role.TOOL message)
                    self._agent_session.messages.append(Message(
                        role=Role.TOOL,
                        content=output,
                        name=tc.name,
                        tool_call_id=tc.id,
                    ))

                    # Show result in chat
                    self.add_message(
                        "assistant",
                        f"[green]✓[/green] {tc.name}\n[dim]{output[:500]}[/dim]",
                    )

            # Show context usage
            current_msgs = self.agent._build_messages(self._agent_session)
            total_tokens = self.agent.estimate_tokens(current_msgs)
            max_ctx = self.config.context.max_tokens
            usage_pct = (total_tokens / max_ctx) * 100
            color = "red" if usage_pct > 80 else "yellow" if usage_pct > 50 else "green"
            self.add_message(
                "system",
                f"[dim]Context: [{color}]{total_tokens}[/{color}] / {max_ctx} tokens ({usage_pct:.1f}%)[/dim]"
            )

            # Auto-compress if needed
            if self.config.memory.enabled:
                await self._maybe_compress()

        except Exception as e:
            import traceback
            self.add_message("error", f"Fehler: {e}\n{traceback.format_exc()}")
        finally:
            self._thinking = False
            self._focus_input()

    async def _maybe_compress(self):
        """Compress session if history is too long."""
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
        store = SessionSummary(self.config.memory.summary_file)
        store.save(new_summary)

        self.add_message("system", "[dim]✓ Kontext komprimiert.[/dim]")

    # ── Actions ──────────────────────────────────────────────────────────────

    def action_quit(self):
        self.exit()

    def action_clear_chat(self):
        self.messages.clear()
        self._render()
        self.add_message("system", "Chat geleert.")

    def action_show_help(self):
        self._show_help()
