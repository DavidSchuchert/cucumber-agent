"""
CucumberAgent TUI — prompt_toolkit + Rich, modeled after Hermes CLI.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import sys
from datetime import datetime
from io import StringIO

# ─── prompt_toolkit ─────────────────────────────────────────────────────────
from prompt_toolkit import print_formatted_text as _pt_print
from prompt_toolkit.application import Application
from prompt_toolkit.formatted_text import ANSI as _PT_ANSI
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import Layout, HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style as PTStyle
from prompt_toolkit.widgets import TextArea

# ─── Rich ───────────────────────────────────────────────────────────────────
from rich.console import Console
from rich.markdown import Markdown

# ─── Cucumber ───────────────────────────────────────────────────────────────
from cucumber_agent.config import Config
from cucumber_agent.agent import Agent


# ─── Colors ─────────────────────────────────────────────────────────────────

C_BG       = "#0b0e14"
C_INPUTBG  = "#111827"
C_GREEN    = "#4ade80"
C_CYAN     = "#38bdf8"
C_YELLOW   = "#fbbf24"
C_RED      = "#f87171"
C_DIM      = "#64748b"
C_ORANGE   = "#fb923c"
C_USER     = "#bbf7d0"
C_TS       = "#475569"
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
        self._messages.append({
            "role": "tool", "name": name, "args": args,
            "output": output, "ts": datetime.now()
        })

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
                prefix = f"[#4ade80 bold]>[/] " if i == 0 else "  "
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
                for k, v in args.items() if k != "reason"
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
        import sys as _sys
        _sys.stderr.write("DEBUG: CucumberTUI.__init__ gestartet\n")
        _sys.stderr.flush()
        self.agent = agent
        self.config = config
        self._w = _term_width()
        _sys.stderr.write(f"DEBUG: term_width={self._w}\n")
        _sys.stderr.flush()
        self.history = MessageHistory(self._w)
        _sys.stderr.write("DEBUG: MessageHistory erstellt\n")
        _sys.stderr.flush()
        self._running = False
        self._session = None
        self._skill_loader = None
        self._facts = None
        self._ansi_obj = _PT_ANSI("")
        _sys.stderr.write("DEBUG: Variablen init\n")
        _sys.stderr.flush()

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
        _sys.stderr.write("DEBUG: Output window erstellt\n")
        _sys.stderr.flush()

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
        _sys.stderr.write("DEBUG: Input widget erstellt\n")
        _sys.stderr.flush()

        self._root = HSplit([self._output_window, self._input_widget])
        _sys.stderr.write("DEBUG: HSplit erstellt\n")
        _sys.stderr.flush()

        self._kb = KeyBindings()
        @self._kb.add(Keys.ControlC, eager=True)
        def _quit(event):
            event.app.exit()
        @self._kb.add(Keys.ControlL, eager=True)
        def _clear(event):
            self.history.clear()
            self._refresh_output()
        _sys.stderr.write("DEBUG: KeyBindings erstellt\n")
        _sys.stderr.flush()

        self._app = Application(
            layout=Layout(self._root),
            key_bindings=self._kb,
            style=PTStyle.from_dict({
                "wrapper":          "#e2e8f0 bg:{bg}".format(bg=C_BG),
                "output-field":     "#e2e8f0 bg:{bg}".format(bg=C_BG),
                "input-field":      f"#e2e8f0 bg:{C_INPUTBG}",
                "text-area":        f"#e2e8f0 bg:{C_INPUTBG}",
                "cursor":           "bg:#4ade80 #0b0e14",
            }),
            erase_when_done=False,
        )
        _sys.stderr.write("DEBUG: Application erstellt — __init__ FERTIG\n")
        _sys.stderr.flush()

    # ── Public API ─────────────────────────────────────────────────────────

    def run(self):
        import sys as _sys
        _sys.stderr.write("DEBUG: run() gestartet\n")
        _sys.stderr.flush()
        # NOTE: Banner printed INSIDE patch_stdout() context (see Hermes pattern)
        self._init_agent_session()
        _sys.stderr.write("DEBUG: session init fertig\n")
        _sys.stderr.flush()
        self._refresh_output()
        _sys.stderr.write("DEBUG: output refresh fertig, starte app.run()\n")
        _sys.stderr.flush()
        with patch_stdout():
            self._print_banner()
            _sys.stderr.write("DEBUG: banner fertig\n")
            _sys.stderr.flush()
            self._running = True
            self._app.run()
        _sys.stderr.write("DEBUG: app beendet\n")
        _sys.stderr.flush()

    # ── _cprint: Rich markup → Console → ANSI → PT_ANSI → print_formatted_text ──

    def _cprint(self, text: str):
        import sys as _sys
        if not text:
            return
        _sys.stderr.write(f"DEBUG _cprint: {text[:50]}\n")
        _sys.stderr.flush()
        buf = StringIO()
        inner = Console(
            file=buf,
            force_terminal=True,
            color_system="truecolor",
            highlight=False,
            width=self._w,
        )
        inner.print(text)
        ansi_str = buf.getvalue().rstrip()
        _sys.stderr.write(f"DEBUG _cprint: ANSI len={len(ansi_str)}\n")
        _sys.stderr.flush()
        if ansi_str:
            _pt_print(_PT_ANSI(ansi_str))
        _sys.stderr.write("DEBUG _cprint: done\n")
        _sys.stderr.flush()

    # ── Banner ─────────────────────────────────────────────────────────────

    def _print_banner(self):
        import sys as _sys
        _sys.stderr.write("DEBUG: _print_banner()\n")
        _sys.stderr.flush()
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
        _sys.stderr.write("DEBUG: _print_banner() fertig\n")
        _sys.stderr.flush()

    # ── Output refresh ─────────────────────────────────────────────────────

    def _refresh_output(self):
        """Re-render message history to ANSI and schedule a UI redraw."""
        ansi_str = self.history.render_to_ansi()
        self._ansi_obj = _PT_ANSI(ansi_str) if ansi_str else _PT_ANSI("")
        self._app.invalidate()

    # ── Session init ───────────────────────────────────────────────────────

    def _init_agent_session(self):
        import sys as _sys
        _sys.stderr.write("DEBUG: _init_agent_session()\n")
        _sys.stderr.flush()
        from cucumber_agent.memory import FactsStore, SessionSummary
        from cucumber_agent.session import Session
        from cucumber_agent.workspace import WorkspaceDetector
        from cucumber_agent import tools as tools_module
        _sys.stderr.write("DEBUG: imports ok\n")
        _sys.stderr.flush()

        self._session = Session(id="tui", model=self.config.agent.model)
        _sys.stderr.write("DEBUG: session created\n")
        _sys.stderr.flush()

        ws = WorkspaceDetector.detect(self.config.workspace)
        self._session.metadata["workspace"] = ws.to_context_string()
        _sys.stderr.write("DEBUG: workspace ok\n")
        _sys.stderr.flush()

        self._facts = FactsStore(self.config.memory.facts_file)
        self._session.metadata["facts_context"] = self._facts.to_context_string()
        _sys.stderr.write("DEBUG: facts ok\n")
        _sys.stderr.flush()

        config_dir = self.config.config_dir
        wiki_dir = self.config.workspace / "wiki"
        self._session.metadata["agent_context"] = (
            f"Agent Home: {config_dir} | "
            f"Personality File: {config_dir}/personality/personality.md | "
            f"Custom Tools: {config_dir}/custom_tools | "
            f"Project Wiki: {wiki_dir}"
        )
        _sys.stderr.write("DEBUG: agent_context ok\n")
        _sys.stderr.flush()

        if self.config.memory.enabled:
            summary_store = SessionSummary(self.config.memory.summary_file)
            summary = summary_store.load()
            if not summary:
                from cucumber_agent.session_logger import SessionLogger
                logger = SessionLogger(self.config.memory.log_dir)
                summary = logger.get_recent_summary(days=3, max_entries=10)
            if summary:
                self._session.metadata["summary"] = summary
            _sys.stderr.write("DEBUG: summary ok\n")
            _sys.stderr.flush()

        from cucumber_agent.skills import SkillLoader
        self._skill_loader = SkillLoader()
        self._skill_loader.load_all()
        _sys.stderr.write("DEBUG: skills loaded\n")
        _sys.stderr.flush()

        self._custom_tool_loader = tools_module.CustomToolLoader()
        self._custom_tool_loader.load_all()
        _sys.stderr.write("DEBUG: tools loaded — _init_agent_session FERTIG\n")
        _sys.stderr.flush()

    # ── Input handling ────────────────────────────────────────────────────

    def _on_input(self, buffer) -> None:
        """Called by TextArea when user presses Enter."""
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

        if command in ("/exit", "/quit"):
            self._app.exit()
        elif command in ("/clear",):
            self.history.clear()
            self._refresh_output()
        elif command in ("/help",):
            self._show_help()
        elif command == "/config":
            cfg = self.config.agent
            self._cprint(f"[cyan]Provider:[/cyan] {cfg.provider}")
            self._cprint(f"[cyan]Model:[/cyan] {cfg.model}")
            self._cprint(f"[cyan]Temperature:[/cyan] {cfg.temperature}")
        elif command == "/memory":
            facts = self._facts.all()
            if facts:
                for k, v in facts.items():
                    self._cprint(f"[cyan]{k}[/cyan]: {v}")
            else:
                self._cprint("[dim italic]Keine Fakten gespeichert.[/dim italic]")
        elif command == "/skills":
            if self._skill_loader and self._skill_loader.skills:
                for s in self._skill_loader.skills:
                    self._cprint(f"[cyan]{s.command}[/cyan]: {s.description[:60]}")
            else:
                self._cprint("[dim italic]Keine Skills installiert.[/dim italic]")
        elif command == "/context":
            msgs = self.agent._build_messages(self._session)
            tokens = self.agent.estimate_tokens(msgs)
            max_ctx = self.config.context.max_tokens
            pct = (tokens / max_ctx) * 100
            color = "red" if pct > 80 else "yellow" if pct > 50 else "green"
            self._cprint(f"[cyan]Nachrichten:[/cyan] {len(self._session.messages)}")
            self._cprint(f"[cyan]Tokens:[/cyan] [{color}]{tokens}[/{color}] / {max_ctx} ({pct:.1f}%)")
        else:
            self._cprint(f"[red]Unbekannter Befehl:[/red] {command}")

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
        self.history.add_user(user_input)
        self._cprint(f"[dim]Nachricht gesendet…[/]")
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
                        result = await self.agent.tools.execute(tc.name, **tc.arguments)
                        output = result.output if result.success else f"ERROR: {result.error or result.output}"
                    except Exception as e:
                        output = f"EXCEPTION: {e}"

                    from cucumber_agent.session import Message, Role
                    self._session.messages.append(Message(
                        role=Role.TOOL, content=output, name=tc.name, tool_call_id=tc.id
                    ))
                    self.history.add_tool(tc.name, tc.arguments, output)
                    self._refresh_output()

            msgs = self.agent._build_messages(self._session)
            tokens = self.agent.estimate_tokens(msgs)
            max_ctx = self.config.context.max_tokens
            pct = (tokens / max_ctx) * 100
            color = "red" if pct > 80 else "yellow" if pct > 50 else "green"
            self._cprint(f"[dim]Context: [{color}]{tokens}[/{color}] / {max_ctx} tokens ({pct:.1f}%)[/dim]")

            if self.config.memory.enabled:
                await self._maybe_compress()

        except Exception as e:
            import traceback
            self.history.add_error(f"Fehler: {e}")
            self._cprint(f"[dim]{traceback.format_exc()[:200]}[/dim]")
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
        self._cprint(f"[dim italic]✓ Kontext komprimiert.[/dim italic]")
