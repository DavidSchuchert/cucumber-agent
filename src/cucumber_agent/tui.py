"""
CucumberAgent TUI — prompt_toolkit + Rich, modeled after Hermes CLI.
"""

from __future__ import annotations

import asyncio
import re
import shutil
from datetime import datetime
from io import StringIO
from pathlib import Path

# ─── prompt_toolkit ─────────────────────────────────────────────────────────
from prompt_toolkit import print_formatted_text as _pt_print
from prompt_toolkit.application import Application
from prompt_toolkit.formatted_text import ANSI as _PT_ANSI
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style as PTStyle
from prompt_toolkit.widgets import TextArea

# ─── Rich ───────────────────────────────────────────────────────────────────
from rich.console import Console
from rich.markdown import Markdown

from cucumber_agent.agent import Agent

# ─── Cucumber ───────────────────────────────────────────────────────────────
from cucumber_agent.config import Config
from cucumber_agent.tools import ToolRegistry

# ─── Colors ─────────────────────────────────────────────────────────────────

C_BG = "#0b0e14"
C_INPUTBG = "#111827"
C_GREEN = "#4ade80"
C_CYAN = "#38bdf8"
C_YELLOW = "#fbbf24"
C_RED = "#f87171"
C_DIM = "#64748b"
C_ORANGE = "#fb923c"
C_USER = "#bbf7d0"
C_TS = "#475569"
C_TOOL_ARG = "#d4a017"


# ─── Terminal width ─────────────────────────────────────────────────────────


def _term_width() -> int:
    try:
        return shutil.get_terminal_size().columns
    except Exception:
        return 80


# ─── Helpers ───────────────────────────────────────────────────────────────


def _esc(text: str) -> str:
    """Escape [brackets] as literal text for Rich markup."""
    if not text:
        return ""
    result = []
    i = 0
    while i < len(text):
        c = text[i]
        if c == "[":
            result.append("[[")
            i += 1
        elif c == "]":
            result.append("]]")
            i += 1
        else:
            result.append(c)
            i += 1
    return "".join(result)


def _strip_reasoning(text: str) -> str:
    """Remove <think>/<reasoning> blocks from text."""
    for tag in ("think", "thinking", "thought", "reasoning", "reasoning_scratchpad"):
        text = re.sub(rf"<{tag}>.*?</{tag}>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(rf"<{tag}>.*$", "", text, flags=re.DOTALL | re.IGNORECASE)
    return text.strip()


def _wrap(text: str, width: int) -> list[str]:
    """Simple word-wrap."""
    if width <= 0:
        width = 60
    lines = []
    for para in text.split("\n"):
        if not para:
            lines.append("")
            continue
        words = para.split()
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


# ─── Message history ─────────────────────────────────────────────────────────


class MessageHistory:
    """Stores chat messages and renders them as a Rich-ANSI string."""

    def __init__(self, term_width: int):
        self._messages: list[dict] = []
        self._w = term_width

    def add_user(self, text: str):
        self._messages.append({"role": "user", "text": text, "ts": datetime.now()})

    def add_assistant(self, text: str):
        self._messages.append({"role": "assistant", "text": text, "ts": datetime.now()})

    def add_tool(self, name: str, args: dict, output: str):
        self._messages.append(
            {"role": "tool", "name": name, "args": args, "output": output, "ts": datetime.now()}
        )

    def add_error(self, text: str):
        self._messages.append({"role": "error", "text": text, "ts": datetime.now()})

    def add_system(self, text: str):
        self._messages.append({"role": "system", "text": text, "ts": datetime.now()})

    def clear(self):
        self._messages.clear()

    def render_to_ansi(self) -> str:
        """Render the full message history to an ANSI string via Rich Console."""
        if not self._messages:
            return ""

        buf = StringIO()
        inner = Console(
            file=buf,
            force_terminal=True,
            color_system="truecolor",
            highlight=False,
            width=self._w,
        )

        for msg in self._messages:
            self._render_msg(inner, msg)

        return buf.getvalue().rstrip("\n")

    def _render_msg(self, c: Console, msg: dict):
        ts = msg["ts"].strftime("%H:%M")
        role = msg["role"]

        if role == "user":
            wrapped = _wrap(msg["text"], self._w - 10)
            for i, line in enumerate(wrapped):
                prefix = "[#4ade80 bold]>[/] " if i == 0 else "  "
                c.print(f"[#{C_TS}]{ts}[/]  {prefix}[#{C_USER}]{_esc(line)}[/]")

        elif role == "assistant":
            clean = _strip_reasoning(msg["text"])
            if not clean.strip():
                return
            md = Markdown(clean, code_theme="ansi_dark")
            c.print(md)

        elif role == "tool":
            name = msg["name"]
            args = msg.get("args", {})
            output = msg.get("output", "")
            args_s = ", ".join(
                f"[#{C_YELLOW}]{k}[/]=[#{C_TOOL_ARG}]{_esc(str(v)[:60])}[/]"
                for k, v in args.items()
                if k != "reason"
            )
            c.print(
                f"  [#{C_YELLOW}]⚡ {name}[/]"
                + (f"  [#{C_DIM}]({args_s})[/]" if args_s else "")
                + f"  [#{C_TS}]{ts}[/]"
            )
            if output:
                for line in _wrap(output[:300], self._w - 14):
                    c.print(f"    [#{C_DIM}]{_esc(line)}[/]")

        elif role == "error":
            c.print(f"[#{C_RED} bold]✗[/]  [#{C_RED}]{_esc(msg['text'])}[/]  [#{C_TS}]{ts}[/]")

        elif role == "system":
            c.print(f"[#{C_DIM} italic]{msg['text']}[/]  [#{C_TS}]{ts}[/]")


# ─── CucumberTUI ────────────────────────────────────────────────────────────


class CucumberTUI:
    """CucumberAgent TUI — prompt_toolkit + Rich, modeled after Hermes CLI."""

    def __init__(self, agent: Agent, config: Config):
        self.agent = agent
        self.config = config
        self._w = _term_width()
        self.history = MessageHistory(self._w)
        self._running = False
        self._session = None
        self._skill_loader = None
        self._facts = None
        self._ansi_obj = _PT_ANSI("")

        # Output window
        def get_output_text() -> _PT_ANSI:
            return self._ansi_obj

        self._output_control = FormattedTextControl(
            text=get_output_text,
            focusable=False,
            show_cursor=False,
        )
        self._output_window = Window(
            self._output_control,
            style=f"bg:{C_BG} #e2e8f0",
        )

        # Input area
        self._input_widget = TextArea(
            height=Dimension(min=1, max=3, preferred=1),
            style=f"bg:{C_INPUTBG} #e2e8f0",
            multiline=False,
            wrap_lines=True,
            focusable=True,
            history=InMemoryHistory(),
            accept_handler=self._on_input,
        )

        self._root = HSplit([self._output_window, self._input_widget])

        self._kb = KeyBindings()

        @self._kb.add(Keys.ControlC, eager=True)
        def _quit(event):
            event.app.exit()

        @self._kb.add(Keys.ControlL, eager=True)
        def _clear(event):
            self.history.clear()
            self._refresh_output()

        self._app = Application(
            layout=Layout(self._root),
            key_bindings=self._kb,
            style=PTStyle.from_dict(
                {
                    "wrapper": f"#e2e8f0 bg:{C_BG}",
                    "output-field": f"#e2e8f0 bg:{C_BG}",
                    "input-field": f"#e2e8f0 bg:{C_INPUTBG}",
                    "text-area": f"#e2e8f0 bg:{C_INPUTBG}",
                    "cursor": "bg:#4ade80 #0b0e14",
                }
            ),
            erase_when_done=False,
        )

    # ── Public API ─────────────────────────────────────────────────────────

    def run(self):
        # Banner printed to raw stdout before PT app starts
        self._print_banner_raw()
        self._init_agent_session()
        self._refresh_output()
        with patch_stdout():
            self._running = True
            self._app.run()

    # ── _cprint: Rich markup → Console → ANSI → PT_ANSI → print_formatted_text ──

    def _cprint(self, text: str):
        if not text:
            return
        buf = StringIO()
        # NOTE: Rich auto-detects StringIO as non-terminal; no force_terminal needed.
        # Using force_terminal=True can cause deadlocks during prompt_toolkit init.
        inner = Console(
            file=buf,
            color_system="truecolor",
            highlight=False,
            width=self._w,
        )
        inner.print(text)
        ansi_str = buf.getvalue().rstrip()
        if ansi_str:
            _pt_print(_PT_ANSI(ansi_str))

    # ── Banner (raw — before PT starts) ───────────────────────────────────

    def _print_banner_raw(self):
        """Print banner directly to stdout (before PT app is running)."""
        import sys as _sys

        w = self._w
        inner = w - 2
        pers = self.config.personality
        line1 = f"{pers.emoji} {pers.emoji} {pers.name} — CucumberAgent".ljust(inner)[:inner]
        line2 = f"{self.config.agent.provider}/{self.config.agent.model}".ljust(inner)[:inner]
        line3 = "Ctrl+L Clear  Ctrl+C Quit".ljust(inner)[:inner]

        _sys.stdout.write("\n")
        _sys.stdout.write(f"\033[1;32m╔{'═' * inner}╗\033[0m\n")
        _sys.stdout.write(f"\033[1;32m║ \033[1;36m{line1}\033[0m \033[1;32m║\033[0m\n")
        _sys.stdout.write(f"\033[1;32m║ \033[2;37m{line2}\033[0m \033[1;32m║\033[0m\n")
        _sys.stdout.write(f"\033[1;32m║ \033[2;37m{line3}\033[0m \033[1;32m║\033[0m\n")
        _sys.stdout.write(f"\033[1;32m╚{'═' * inner}╝\033[0m\n")
        _sys.stdout.write(
            f"\n\033[1;32m{pers.emoji} {pers.name}\033[0m  \033[2;37m— Chat startklar. Sag was du brauchst!\033[0m\n"
        )
        _sys.stdout.write("\n")
        _sys.stdout.flush()

    # ── Banner (via PT — after app is running) ────────────────────────────

    def _print_banner(self):
        """Print banner through prompt_toolkit's print_formatted_text (after app is live)."""
        w = self._w
        inner = w - 2
        pers = self.config.personality
        line1 = f"{pers.emoji} {pers.emoji} {pers.name} — CucumberAgent".ljust(inner)[:inner]
        line2 = f"{self.config.agent.provider}/{self.config.agent.model}".ljust(inner)[:inner]
        line3 = "[dim]Ctrl+L Clear  Ctrl+C Quit[/dim]".ljust(inner)[:inner]

        for line in (
            "",
            f"[bold {C_GREEN}]╔{'═' * inner}╗[/bold]",
            f"[bold {C_GREEN}]║[reset] {line1}  [{C_GREEN}]║[bold]",
            f"[bold {C_GREEN}]║[reset] [dim]{line2}[/dim]  [{C_GREEN}]║[bold]",
            f"[bold {C_GREEN}]║[reset] [dim]{line3}[/dim]  [{C_GREEN}]║[bold]",
            f"[bold {C_GREEN}]╚{'═' * inner}╝[/bold]",
            "",
            f"[{C_GREEN}]{pers.emoji} {pers.name}[/{C_GREEN}]  [dim]— Chat startklar. Sag was du brauchst![/dim]",
            "",
        ):
            self._cprint(line)

    # ── Output refresh ─────────────────────────────────────────────────────

    def _refresh_output(self):
        """Re-render message history to ANSI and schedule a UI redraw."""
        ansi_str = self.history.render_to_ansi()
        self._ansi_obj = _PT_ANSI(ansi_str) if ansi_str else _PT_ANSI("")
        self._app.invalidate()

    # ── Session init ───────────────────────────────────────────────────────

    def _init_agent_session(self):
        from cucumber_agent import tools as tools_module
        from cucumber_agent.memory import FactsStore, SessionLogger, SessionSummary
        from cucumber_agent.session import Session
        from cucumber_agent.workspace import WorkspaceDetector

        self._session = Session(id="tui", model=self.config.agent.model)

        workspace = self.config.workspace or Path.cwd()
        ws = WorkspaceDetector.detect(workspace)
        self._session.metadata["workspace"] = ws.to_context_string()

        self._facts = FactsStore(self.config.memory.facts_file)
        self._session.metadata["facts_context"] = self._facts.to_context_string()

        config_dir = self.config.config_dir
        wiki_dir = workspace / "wiki"
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
                logger = SessionLogger(self.config.memory.log_dir)
                summary = logger.get_recent_summary(days=3, max_entries=10)
            if summary:
                self._session.metadata["summary"] = summary

        from cucumber_agent.skills import SkillLoader

        self._skill_loader = SkillLoader()
        self._skill_loader.load_all()

        self._custom_tool_loader = tools_module.CustomToolLoader()
        self._custom_tool_loader.load_all()

        # Build capabilities context for the agent
        tools_summary = ToolRegistry.get_capabilities_summary()
        caps_text = "\n".join([f"- {t['name']}: {t['description']}" for t in tools_summary])
        self._session.metadata["capabilities_context"] = caps_text

        if self._skill_loader and self._skill_loader.skills:
            skills_text = "\n".join(
                [f"- {s.command}: {s.description}" for s in self._skill_loader.skills]
            )
            self._session.metadata["skills_context"] = skills_text

    # ── Input handling ────────────────────────────────────────────────────

    def _on_input(self, buffer) -> bool:
        """Called by TextArea when user presses Enter."""
        text = buffer.text.strip()
        buffer.text = ""
        if not text:
            return True
        if text.startswith("/"):
            self._handle_command(text)
        else:
            asyncio.create_task(self._run_chat(text))
        return True

    def _handle_command(self, cmd: str):
        parts = cmd.strip().split(maxsplit=1)
        command = parts[0].lower()

        if command in ("/exit", "/quit"):
            self._app.exit()
        elif command in ("/clear",):
            self.history.clear()
            self._refresh_output()
        elif command in ("/help",):
            for line in (
                "[bold]Commands[/bold]",
                "[cyan]/help[/cyan]     Diese Hilfe",
                "[cyan]/exit[/cyan]     Beenden",
                "[cyan]/clear[/cyan]    Chat leeren",
                "[cyan]/config[/cyan]   Zeige Config",
                "[cyan]/memory[/cyan]    Fakten anzeigen",
                "[cyan]/skills[/cyan]    Verfügbare Skills",
                "[cyan]/context[/cyan]   Context-Status",
                "",
                "[dim]Alles andere = Chat mit dem Agenten[/dim]",
            ):
                self.history.add_system(line)
            self._refresh_output()
        elif command == "/config":
            cfg = self.config.agent
            self.history.add_system(f"[cyan]Provider:[/cyan] {cfg.provider}")
            self.history.add_system(f"[cyan]Model:[/cyan] {cfg.model}")
            self.history.add_system(f"[cyan]Temperature:[/cyan] {cfg.temperature}")
            self._refresh_output()
        elif command == "/memory":
            assert self._facts is not None
            facts = self._facts.all()
            if facts:
                for k, v in facts.items():
                    self.history.add_system(f"[cyan]{k}[/cyan]: {v}")
            else:
                self.history.add_system("[dim italic]Keine Fakten gespeichert.[/dim italic]")
            self._refresh_output()
        elif command == "/skills":
            if self._skill_loader and self._skill_loader.skills:
                for s in self._skill_loader.skills:
                    self.history.add_system(f"[cyan]{s.command}[/cyan]: {s.description[:60]}")
            else:
                self.history.add_system("[dim italic]Keine Skills installiert.[/dim italic]")
            self._refresh_output()
        elif command == "/context":
            assert self._session is not None
            msgs = self.agent._build_messages(self._session)
            tokens = self.agent.estimate_tokens(msgs)
            max_ctx = self.config.context.max_tokens
            pct = (tokens / max_ctx) * 100
            color = "red" if pct > 80 else "yellow" if pct > 50 else "green"
            self.history.add_system(f"[cyan]Nachrichten:[/cyan] {len(self._session.messages)}")
            self.history.add_system(
                f"[cyan]Tokens:[/cyan] [{color}]{tokens}[/{color}] / {max_ctx} ({pct:.1f}%)"
            )
            self._refresh_output()
        else:
            self.history.add_system(f"[red]Unbekannter Befehl:[/red] {command}")
            self._refresh_output()

    def _show_help(self):
        for line in (
            "[bold]Commands[/bold]",
            "[cyan]/help[/cyan]     Diese Hilfe",
            "[cyan]/exit[/cyan]     Beenden",
            "[cyan]/clear[/cyan]    Chat leeren",
            "[cyan]/config[/cyan]   Zeige Config",
            "[cyan]/memory[/cyan]    Fakten anzeigen",
            "[cyan]/skills[/cyan]    Verfügbare Skills",
            "[cyan]/context[/cyan]   Context-Status",
            "",
            "[dim]Alles andere = Chat mit dem Agenten[/dim]",
        ):
            self._cprint(line)

    # ── Agent loop ─────────────────────────────────────────────────────────

    async def _run_chat(self, user_input: str):
        assert self._session is not None
        self.history.add_user(user_input)
        self.history.add_system("[dim]Nachricht gesendet…[/]")
        self._refresh_output()

        try:
            response = await self.agent.run_with_tools(self._session, user_input)

            if response.content:
                clean = _strip_reasoning(response.content)
                if clean.strip():
                    self.history.add_assistant(clean)
                    self._refresh_output()

            if response.tool_calls:
                for tc in response.tool_calls:
                    self.history.add_tool(tc.name, tc.arguments, "Executing…")
                    self._refresh_output()

                    try:
                        result = await ToolRegistry.execute(tc.name, **tc.arguments)
                        output = (
                            result.output
                            if result.success
                            else f"ERROR: {result.error or result.output}"
                        )
                    except Exception as e:
                        output = f"EXCEPTION: {e}"

                    from cucumber_agent.session import Message, Role

                    self._session.messages.append(
                        Message(role=Role.TOOL, content=output, name=tc.name, tool_call_id=tc.id)
                    )
                    self.history.add_tool(tc.name, tc.arguments, output)
                    self._refresh_output()

            msgs = self.agent._build_messages(self._session)
            tokens = self.agent.estimate_tokens(msgs)
            max_ctx = self.config.context.max_tokens
            pct = (tokens / max_ctx) * 100
            color = "red" if pct > 80 else "yellow" if pct > 50 else "green"
            self.history.add_system(
                f"[dim]Context: [{color}]{tokens}[/{color}] / {max_ctx} tokens ({pct:.1f}%)[/dim]"
            )

            if self.config.memory.enabled:
                await self._maybe_compress()

        except Exception as e:
            import traceback

            self.history.add_error(f"Fehler: {e}")
            self.history.add_system(f"[dim]{traceback.format_exc()[:200]}[/dim]")
            self._refresh_output()

    async def _maybe_compress(self):
        assert self._session is not None
        max_msgs = self.config.memory.max_session_messages
        if len(self._session.messages) < max_msgs:
            return
        keep = self.config.memory.summarize_keep_recent
        to_sum = self._session.messages[:-keep]
        remaining = self._session.messages[-keep:]
        new_summary = await self.agent.summarize_messages(to_sum)
        existing = self._session.metadata.get("summary", "")
        combined = (
            existing.strip() + "\n\n[Neuere Zusammenfassung:]\n" + new_summary.strip()
            if existing
            else new_summary.strip()
        )
        self._session.metadata["summary"] = combined
        self._session.messages = remaining
        from cucumber_agent.memory import SessionSummary

        SessionSummary(self.config.memory.summary_file).save(combined)
        self.history.add_system("[dim italic]✓ Kontext komprimiert.[/dim italic]")
        self._refresh_output()
