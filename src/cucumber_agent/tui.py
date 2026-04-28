"""
CucumberAgent Textual TUI — Built with prompt_toolkit, inspired by Hermes CLI / Claude Code.

Architecture:
  - prompt_toolkit Layout: scrolling message buffer (top) + fixed input (bottom)
  - Rich for all text rendering (panels, markdown, colors)
  - patch_stdout context so Rich.print() works inside the interactive loop
  - ChatConsole: Rich Console adapter → _cprint → print_formatted_text(ANSI(...))
"""

from __future__ import annotations

import asyncio
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable

# ─── prompt_toolkit for fixed-input TUI ────────────────────────────────────────
from prompt_toolkit import print_formatted_text as _pt_print
from prompt_toolkit.application import Application
from prompt_toolkit.keys import Keys
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import ANSI as _PT_ANSI
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout, HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style as PTStyle
from prompt_toolkit.widgets import TextArea

# ─── Rich for rendering ────────────────────────────────────────────────────────
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

# ─── Cucumber modules ─────────────────────────────────────────────────────────
from cucumber_agent.config import Config
from cucumber_agent.agent import Agent


# ─── Color scheme (hex for Rich, named for markup) ───────────────────────────

GREEN   = "#4ade80"
CYAN    = "#38bdf8"
YELLOW  = "#fbbf24"
RED     = "#f87171"
DIM     = "#64748b"
BG     = "#0b0e14"

# prompt_toolkit style
PT_STYLE = PTStyle.from_dict({
    "wrapper":          f"bg:{BG} #e2e8f0",
    "input":            f"#4ade80 bold",
    "prompt":           f"#4ade80 bold",
    "tool":             f"#fbbf24",
    "tool-args":        f"#64748b",
    "timestamp":        f"#475569",
    "user-label":       f"#4ade80 bold",
    "assistant-label":  f"#38bdf8 bold",
    "error-label":      f"#f87171 bold",
})


# ─── Helper: ANSI print via prompt_toolkit ─────────────────────────────────────

def _cprint(text: str):
    """Print ANSI-colored text through prompt_toolkit's native renderer.

    Raw ANSI escapes via print() are swallowed by patch_stdout's StdoutProxy.
    Routing through print_formatted_text(ANSI(...)) lets prompt_toolkit parse
    the escapes and render real colors.
    """
    _pt_print(_PT_ANSI(text))


# ─── ChatConsole: Rich adapter for patch_stdout context ───────────────────────

class ChatConsole:
    """Rich Console adapter for prompt_toolkit's patch_stdout context.

    Captures Rich's rendered ANSI output and routes it through _cprint
    so colors and markup render correctly inside the interactive chat loop.
    """

    def __init__(self):
        from io import StringIO
        self._buffer = StringIO()
        self._inner = Console(
            file=self._buffer,
            force_terminal=True,
            color_system="truecolor",
            highlight=False,
            width=_terminal_width(),
        )

    def print(self, *args, **kwargs):
        self._buffer.seek(0)
        self._buffer.truncate()
        self._inner.width = _terminal_width()
        self._inner.print(*args, **kwargs)
        output = self._buffer.getvalue()
        for line in output.rstrip("\n").split("\n"):
            if line.strip():
                _cprint(line)

    def rule(self, style: str = "dim"):
        _cprint(f"[{style}]{'─' * _terminal_width()}[/]")

    def status(self, *args, **kwargs):
        """No-op status (busy indicator handled by TUI loop)."""
        yield self

    @property
    def width(self):
        return _terminal_width()


def _terminal_width() -> int:
    try:
        return shutil.get_terminal_size().columns
    except Exception:
        return 80


# ─── Message buffer ────────────────────────────────────────────────────────────

class MessageBuffer:
    """Holds the chat history as styled ANSI strings for prompt_toolkit."""

    def __init__(self, console: ChatConsole):
        self._lines: list[str] = []
        self._console = console
        self._last_input_height = 0

    def add_user(self, text: str, ts: datetime):
        time_str = ts.strftime("%H:%M")
        # Wrap long lines
        width = self._console.width - 10
        wrapped = _wrap_lines(text, width)
        for line in wrapped:
            self._lines.append(
                f"[#475569]{time_str}[/]  [#4ade80 bold]>[/] [#bbf7d0]{_esc_markup(line)}[/]"
            )

    def add_assistant(self, text: str, ts: datetime, name: str = "Herbert"):
        time_str = ts.strftime("%H:%M")
        # Strip reasoning/thinking blocks
        clean = _strip_reasoning(text)
        # Render as markdown
        rendered = self._render_markdown(clean)
        # Wrap long lines
        wrapped = _wrap_lines(rendered, self._console.width - 10)
        prefix = f"[#38bdf8 bold]{name}[/]"
        for i, line in enumerate(wrapped):
            if i == 0:
                self._lines.append(f"  {line}  [#475569]{time_str}[/]")
            else:
                self._lines.append(f"  {line}")

    def add_tool(self, name: str, args: dict, output: str, ts: datetime):
        time_str = ts.strftime("%H:%M")
        args_s = ", ".join(
            f"[#fbbf24]{k}[/]=[#d4a017]{_esc_markup(str(v)[:60])}[/]"
            for k, v in args.items() if k != "reason"
        )
        self._lines.append(
            f"  [#fbbf24]⚡ {name}[/]"
            + (f"  [#64748b]({args_s})[/]" if args_s else "")
            + f"  [#475569]{time_str}[/]"
        )
        for line in _wrap_lines(_esc_markup(output[:300]), self._console.width - 14):
            self._lines.append(f"    [#64748b]{line}[/]")

    def add_error(self, text: str, ts: datetime):
        time_str = ts.strftime("%H:%M")
        self._lines.append(f"[#f87171]✗[/] {_esc_markup(text)}  [#475569]{time_str}[/]")

    def add_system(self, text: str, ts: datetime):
        time_str = ts.strftime("%H:%M")
        self._lines.append(f"[#64748b italic]{text}[/]  {time_str}")

    def add_blank(self):
        self._lines.append("")

    def clear(self):
        self._lines.clear()

    def get_formatted_text(self) -> list[tuple[str, str]]:
        """Return list of (style, text) tuples for FormattedTextControl."""
        result = []
        for line in self._lines:
            result.append((line, line))
        return result

    def _render_markdown(self, text: str) -> str:
        """Render text as markdown, returning ANSI-colored string."""
        if not text.strip():
            return ""
        buf = ""
        md = Markdown(text, code_theme="monokai")
        # Render through Rich
        from io import StringIO
        tmp_buf = StringIO()
        c = Console(file=tmp_buf, force_terminal=True, color_system="truecolor", width=self._console.width - 10)
        c.print(md)
        ansi_output = tmp_buf.getvalue()
        # Convert to prompt_toolkit-compatible ANSI
        # Strip the \r\n that Rich adds
        for line in ansi_output.rstrip("\n").split("\n"):
            if line.strip():
                buf += line + "\n"
        return buf.rstrip("\n")

    def __len__(self):
        return len(self._lines)


def _esc_markup(text: str) -> str:
    """Escape [brackets] so they're treated as literal text."""
    if not text:
        return ""
    result = ""
    i = 0
    while i < len(text):
        c = text[i]
        if c == "[":
            # Check if this looks like a Rich tag
            if i + 1 < len(text) and text[i+1].isalpha():
                result += "[["
            else:
                result += "[["
            i += 1
        elif c == "]":
            result += "]]"
            i += 1
        else:
            result += c
            i += 1
    return result


def _strip_reasoning(text: str) -> str:
    """Remove <think>/<think> blocks from text."""
    for tag in ("think", "thinking", "thought", "reasoning", "REASONING_SCRATCHPAD"):
        text = re.sub(rf"<{tag}>.*?</{tag}>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(rf"<{tag}>.*$", "", text, flags=re.DOTALL | re.IGNORECASE)
    return text.strip()


def _wrap_lines(text: str, width: int) -> list[str]:
    """Simple word-wrap at width."""
    if width <= 0:
        width = 60
    lines = []
    for paragraph in text.split("\n"):
        if not paragraph:
            lines.append("")
            continue
        words = paragraph.split()
        current = ""
        for word in words:
            if not current:
                current = word
            elif len(current) + 1 + len(word) <= width:
                current += " " + word
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
    return lines or [""]


# ─── TUI Application ───────────────────────────────────────────────────────────

class CucumberTUI:
    """CucumberAgent TUI — prompt_toolkit + Rich, modeled after Hermes CLI."""

    BANNER = f"""
[bold {GREEN}]╔═[/{GREEN}][bold {GREEN}] HERBERT OPA — CUCUMBER AGENT [/{GREEN}][bold {GREEN}]═╗[/]
[bold {GREEN}]╚[/{GREEN}]""".strip()

    def __init__(self, agent: Agent, config: Config):
        self.agent = agent
        self.config = config
        self.console = ChatConsole()
        self.msg_buf = MessageBuffer(self.console)
        self._running = False
        self._skill_loader = None
        self._facts = None

        # ── prompt_toolkit layout ──────────────────────────────────────────────
        self._history = InMemoryHistory()
        self._input_buffer = Buffer(
            history=self._history,
            multiline=False,
            accept_handler=self._on_input_submit,
        )

        self._output_control = FormattedTextControl(
            text=self.msg_buf.get_formatted_text,
        )
        self._output_window = Window(
            self._output_control,
            always_hide_cursor=True,
            style="bg:#0b0e14 #e2e8f0",
        )

        self._input_window = Window(
            FormattedTextControl([
                (f"[#4ade80 bold]>[/] ", "> "),
            ]),
            width=Dimension(preferred=3),
            height=Dimension(preferred=1),
            style="bg:#111827",
        )

        self._root_container = HSplit([
            self._output_window,
            self._input_window,
        ])

        self._kb = KeyBindings()

        @self._kb.add(Keys.ControlC, eager=True)
        def _quit(event):
            event.app.exit()

        @self._kb.add(Keys.ControlL, eager=True)
        def _clear(event):
            self.msg_buf.clear()
            self._refresh_output()

        self._app = Application(
            layout=Layout(self._root_container),
            key_bindings=self._kb,
            style=PT_STYLE,
            erase_when_done=False,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def run(self):
        """Launch the TUI."""
        self._print_banner()
        self._init_agent_session()

        with patch_stdout():
            self._running = True
            self._app.run()

    # ── Initialization ──────────────────────────────────────────────────────

    def _print_banner(self):
        pers = self.config.personality
        w = _terminal_width()
        inner = w - 2
        line1 = f"{pers.emoji} {pers.name} — CucumberAgent".ljust(inner)[:inner]
        line2 = f"{self.config.agent.provider}/{self.config.agent.model}".ljust(inner)[:inner]
        line3 = "[dim]Ctrl+L Clear  Ctrl+C Quit[/dim]".ljust(inner)[:inner]

        _cprint("")
        _cprint(f"[bold {GREEN}]╔{'═' * inner}╗[/]")
        _cprint(f"[bold {GREEN}]║[/] [#38bdf8 bold]{line1}[/] [bold {GREEN}]║[/]")
        _cprint(f"[bold {GREEN}]║[/] [#64748b]{line2}[/] [bold {GREEN}]║[/]")
        _cprint(f"[bold {GREEN}]║[/] [#64748b]{line3}[/] [bold {GREEN}]║[/]")
        _cprint(f"[bold {GREEN}]╚{'═' * inner}╝[/]")
        _cprint("")
        _cprint(f"[#4ade80]{pers.emoji} {pers.name}[/]  [dim]— Chat startklar. Sag was du brauchst![/]")
        _cprint("")

    def _init_agent_session(self):
        """Initialize session, memory, skills."""
        from cucumber_agent.memory import FactsStore, SessionSummary
        from cucumber_agent.session import Session
        from cucumber_agent.workspace import WorkspaceDetector
        from cucumber_agent import tools as tools_module

        self._session = Session(id="tui", model=self.config.agent.model)

        ws = WorkspaceDetector.detect(self.config.workspace)
        self._session.metadata["workspace"] = ws.to_context_string()

        self._facts = FactsStore(self.config.memory.facts_file)
        self._session.metadata["facts_context"] = self._facts.to_context_string()

        config_dir = self.config.config_dir
        wiki_dir = self.config.workspace / "wiki"
        self._session.metadata["agent_context"] = (
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
                self._session.metadata["summary"] = summary

        from cucumber_agent.skills import SkillLoader
        self._skill_loader = SkillLoader()
        self._skill_loader.load_all()

        self._custom_tool_loader = tools_module.CustomToolLoader()
        self._custom_tool_loader.load_all()

    # ── Input handling ───────────────────────────────────────────────────────

    def _on_input_submit(self, buffer: Buffer) -> None:
        text = buffer.text.strip()
        buffer.text = ""
        if not text:
            return
        if text.startswith("/"):
            self._handle_command(text)
        else:
            asyncio.create_task(self._run_chat(text))

    def _handle_command(self, cmd: str):
        parts = cmd.strip().split(maxsplit=1)
        command = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if command in ("/exit", "/quit", "/q"):
            self._app.exit()
        elif command in ("/clear", "/cls"):
            self.msg_buf.clear()
            self._refresh_output()
            self._print_system("Chat geleert.")
        elif command in ("/help", "/h", "/?"):
            self._show_help()
        elif command == "/config":
            cfg = self.config.agent
            self._print_system(
                f"[cyan]Provider:[/cyan] {cfg.provider}\n"
                f"[cyan]Model:[/cyan] {cfg.model}\n"
                f"[cyan]Temperature:[/cyan] {cfg.temperature}"
            )
        elif command == "/memory":
            facts = self._facts.all()
            if facts:
                lines = "\n".join(f"[cyan]{k}[/cyan]: {v}" for k, v in facts.items())
                self._print_system(lines)
            else:
                self._print_system("[dim]Keine Fakten gespeichert.[/dim]")
        elif command == "/skills":
            if self._skill_loader and self._skill_loader.skills:
                lines = "\n".join(
                    f"[cyan]{s.command}[/cyan]: {s.description[:60]}"
                    for s in self._skill_loader.skills
                )
                self._print_system(lines)
            else:
                self._print_system("[dim]Keine Skills installiert.[/dim]")
        elif command == "/context":
            msgs = self.agent._build_messages(self._session)
            tokens = self.agent.estimate_tokens(msgs)
            max_ctx = self.config.context.max_tokens
            pct = (tokens / max_ctx) * 100
            color = "red" if pct > 80 else "yellow" if pct > 50 else "green"
            self._print_system(
                f"[cyan]Nachrichten:[/cyan] {len(self._session.messages)}\n"
                f"[cyan]Tokens:[/cyan] [{color}]{tokens}[/{color}] / {max_ctx} ({pct:.1f}%)"
            )
        else:
            self._print_system(f"[red]Unbekannter Befehl:[/red] {command}")

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
        for line in lines:
            self._print_system(line)

    # ── Agent loop ───────────────────────────────────────────────────────────

    async def _run_chat(self, user_input: str):
        from cucumber_agent.session import Message, Role
        from cucumber_agent.tools import ToolRegistry
        import re

        ts = datetime.now()
        self.msg_buf.add_user(user_input, ts)
        self.msg_buf.add_blank()
        self._refresh_output()

        try:
            response = await self.agent.run_with_tools(self._session, user_input)

            if response.content and response.content.strip():
                clean = _strip_reasoning(response.content).strip()
                if clean:
                    self.msg_buf.add_assistant(clean, datetime.now(), self.config.personality.name)
                    self.msg_buf.add_blank()
                    self._refresh_output()

            if response.tool_calls:
                for tc in response.tool_calls:
                    ts_tc = datetime.now()
                    self.msg_buf.add_tool(tc.name, tc.arguments, "Executing...", ts_tc)
                    self._refresh_output()

                    try:
                        result = await ToolRegistry.execute(tc.name, **tc.arguments)
                        output = result.output if result.success else f"ERROR: {result.error or result.output}"
                    except Exception as e:
                        output = f"EXCEPTION: {e}"

                    self._session.messages.append(Message(
                        role=Role.TOOL, content=output, name=tc.name, tool_call_id=tc.id
                    ))
                    self.msg_buf.add_tool(tc.name, tc.arguments, output, datetime.now())
                    self.msg_buf.add_assistant(
                        f"[green]✓[/green] {tc.name}\n{output[:300]}",
                        datetime.now(),
                        self.config.personality.name
                    )
                    self.msg_buf.add_blank()
                    self._refresh_output()

            # Context usage
            current_msgs = self.agent._build_messages(self._session)
            total_tokens = self.agent.estimate_tokens(current_msgs)
            max_ctx = self.config.context.max_tokens
            usage_pct = (total_tokens / max_ctx) * 100
            color = "red" if usage_pct > 80 else "yellow" if usage_pct > 50 else "green"
            self._print_system(
                f"[dim]Context: [{color}]{total_tokens}[/{color}] / {max_ctx} tokens ({usage_pct:.1f}%)[/dim]"
            )

            if self.config.memory.enabled:
                await self._maybe_compress()

        except Exception as e:
            import traceback
            self.msg_buf.add_error(f"Fehler: {e}", datetime.now())
            self._print_system(f"[dim]{traceback.format_exc()[:200]}[/dim]")
            self.msg_buf.add_blank()
            self._refresh_output()

    async def _maybe_compress(self):
        max_msgs = self.config.memory.max_session_messages
        if len(self._session.messages) < max_msgs:
            return
        keep = self.config.memory.summarize_keep_recent
        to_sum = self._session.messages[:-keep]
        remaining = self._session.messages[-keep:]
        new_summary = await self.agent.summarize_messages(to_sum)
        self._session.metadata["summary"] = new_summary
        self._session.messages = remaining
        from cucumber_agent.memory import SessionSummary
        SessionSummary(self.config.memory.summary_file).save(new_summary)
        self._print_system("[dim]✓ Kontext komprimiert.[/dim]")
        self._refresh_output()

    # ── Output helpers ───────────────────────────────────────────────────────

    def _refresh_output(self):
        """Re-render the message buffer to the output window."""
        self._output_control.text = self.msg_buf.get_formatted_text()

    def _print_system(self, text: str):
        self.msg_buf.add_system(text, datetime.now())
        self._refresh_output()
