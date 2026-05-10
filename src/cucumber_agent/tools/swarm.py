"""Herbert Swarm — native multi-agent project builder, integrated into cucumber-agent."""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from cucumber_agent.session import Message, Role
from cucumber_agent.tools.base import BaseTool, ToolResult
from cucumber_agent.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)
console = Console()

# ---------------------------------------------------------------------------
# Brain storage helpers
# ---------------------------------------------------------------------------

_brain_file_lock = asyncio.Lock()
_SWARM_HOME = Path.home() / ".local" / "share" / "cucumber-swarm"


def _brain_file_for(project_path: str | Path | None) -> Path:
    if project_path:
        return Path(project_path).resolve() / ".swarm_brain.json"
    return _SWARM_HOME / "brain.json"


async def _load_brain(brain_file: Path) -> dict | None:
    if not brain_file.exists():
        return None
    async with _brain_file_lock:
        try:
            return json.loads(brain_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to load brain file {brain_file}: {e}")
            return None


async def _save_brain(brain: dict, brain_file: Path) -> None:
    async with _brain_file_lock:
        try:
            brain_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = brain_file.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(brain, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(brain_file)
        except OSError as e:
            logger.error(f"Failed to save brain file {brain_file}: {e}")


# ---------------------------------------------------------------------------
# Project analysis + planning
# ---------------------------------------------------------------------------

_ALLOWED_AGENT_ROLES = {"planner", "coder", "reviewer", "tester", "devops", "designer"}
_MAX_PLANNER_FILES = 160
_MAX_PLAN_TASKS = 40

_ROLE_COLORS = {
    "coder": "green",
    "tester": "yellow",
    "reviewer": "magenta",
    "planner": "cyan",
    "devops": "blue",
    "designer": "bright_magenta",
}


def _scan_project_files(project_path: Path) -> set[str]:
    """Scan project root and return a set of lowercase filenames/dirnames."""
    files: set[str] = set()
    try:
        for entry in project_path.iterdir():
            files.add(entry.name.lower())
            if entry.is_dir():
                for sub in entry.iterdir():
                    files.add(f"{entry.name.lower()}/{sub.name.lower()}")
    except PermissionError:
        pass
    return files


def _planner_file_inventory(project_path: Path) -> list[str]:
    """Return a compact project inventory for the LLM planner."""
    ignored_dirs = {
        ".git",
        ".hg",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".swarm",
        ".venv",
        "__pycache__",
        "dist",
        "build",
        "node_modules",
        "vendor",
    }
    ignored_suffixes = {".db", ".sqlite", ".sqlite3", ".pyc", ".png", ".jpg", ".jpeg", ".gif"}
    inventory: list[str] = []

    if not project_path.exists():
        return inventory

    for path in sorted(project_path.rglob("*")):
        if len(inventory) >= _MAX_PLANNER_FILES:
            break
        rel = path.relative_to(project_path)
        if any(part in ignored_dirs for part in rel.parts):
            continue
        if path.is_file() and path.suffix.lower() in ignored_suffixes:
            continue
        suffix = "/" if path.is_dir() else ""
        inventory.append(f"{rel.as_posix()}{suffix}")

    return inventory


def _extract_json_object(text: str) -> dict:
    """Extract a JSON object from a model response."""
    content = (text or "").strip()
    if "```json" in content:
        content = content.split("```json", 1)[1].split("```", 1)[0]
    elif "```" in content:
        content = content.split("```", 1)[1].split("```", 1)[0]

    try:
        parsed = json.loads(content.strip())
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        parsed = json.loads(content[start : end + 1])

    if not isinstance(parsed, dict):
        raise ValueError("Planner response must be a JSON object")
    return parsed


def _clean_phase_name(value: object) -> str:
    phase = str(value or "").strip().upper().replace(" ", "_").replace("-", "_")
    return phase[:40]


def _clean_task_files(raw_files: object) -> list[str]:
    if not isinstance(raw_files, list):
        return []

    files: list[str] = []
    for raw in raw_files[:12]:
        file_path = str(raw or "").strip().replace("\\", "/")
        if not file_path or file_path.startswith("/") or ".." in Path(file_path).parts:
            continue
        files.append(file_path[:180])
    return files


def _generic_ai_unavailable_plan() -> tuple[dict, list[str]]:
    """Create a neutral fallback when the LLM planner is technically unavailable."""
    return {
        "task-001": {
            "id": "task-001",
            "description": "Implement the project requirements described in SPEC.md",
            "agent_role": "coder",
            "files": ["README.md"],
            "dependencies": [],
            "status": "pending",
            "priority": 1,
            "phase": 1,
            "created_by": "planner-fallback",
        }
    }, ["IMPLEMENTATION"]


def _normalize_llm_plan(plan: dict) -> tuple[dict, list[str]]:
    """Validate and normalize an LLM-created swarm plan."""
    raw_phases = plan.get("phases", [])
    if not isinstance(raw_phases, list):
        raw_phases = []

    phases: list[str] = []
    for raw_phase in raw_phases:
        phase = _clean_phase_name(raw_phase)
        if phase and phase not in phases:
            phases.append(phase)

    raw_tasks = plan.get("tasks", [])
    if not isinstance(raw_tasks, list):
        raw_tasks = []

    tasks: dict = {}
    llm_id_to_task_id: dict[str, str] = {}
    pending_dependencies: dict[str, list[str]] = {}

    for raw_task in raw_tasks[:_MAX_PLAN_TASKS]:
        if not isinstance(raw_task, dict):
            continue

        description = str(raw_task.get("description") or "").strip()
        if not description:
            continue

        role = str(raw_task.get("agent_role") or "coder").strip().lower()
        if role not in _ALLOWED_AGENT_ROLES:
            role = "coder"

        raw_phase = raw_task.get("phase", 1)
        phase_num: int
        if isinstance(raw_phase, int):
            phase_num = raw_phase
        else:
            phase_name = _clean_phase_name(raw_phase)
            if phase_name and phase_name not in phases:
                phases.append(phase_name)
            phase_num = phases.index(phase_name) + 1 if phase_name in phases else 1

        if not phases:
            phases.append("IMPLEMENTATION")
        phase_num = min(max(phase_num, 1), len(phases))

        task_id = f"task-{len(tasks) + 1:03d}"
        llm_task_id = str(raw_task.get("id") or task_id).strip()
        llm_id_to_task_id[llm_task_id] = task_id

        priority_raw = raw_task.get("priority", len(tasks) + 1)
        try:
            priority = int(priority_raw)
        except (TypeError, ValueError):
            priority = len(tasks) + 1

        dependencies = raw_task.get("dependencies", raw_task.get("depends_on", []))
        if not isinstance(dependencies, list):
            dependencies = []

        tasks[task_id] = {
            "id": task_id,
            "description": description[:400],
            "agent_role": role,
            "files": _clean_task_files(raw_task.get("files", [])),
            "dependencies": [],
            "status": "pending",
            "priority": priority,
            "phase": phase_num,
            "created_by": "ai-planner",
        }
        pending_dependencies[task_id] = [
            str(dep).strip() for dep in dependencies if str(dep).strip()
        ]

    if not tasks:
        return _generic_ai_unavailable_plan()

    for task_id, deps in pending_dependencies.items():
        normalized_deps = []
        for dep in deps:
            mapped = llm_id_to_task_id.get(dep, dep if dep in tasks else None)
            if mapped and mapped != task_id and mapped not in normalized_deps:
                normalized_deps.append(mapped)
        tasks[task_id]["dependencies"] = normalized_deps

    used_phase_numbers = {task["phase"] for task in tasks.values()}
    compact_phases = [phase for i, phase in enumerate(phases, 1) if i in used_phase_numbers]
    phase_number_map = {
        old_num: new_num for new_num, old_num in enumerate(sorted(used_phase_numbers), 1)
    }
    for task in tasks.values():
        task["phase"] = phase_number_map[task["phase"]]

    return tasks, compact_phases or ["IMPLEMENTATION"]


async def _llm_create_task_plan(spec_content: str, project_path: Path) -> dict:
    """Ask the configured LLM to create the complete swarm task plan."""
    from cucumber_agent.agent import Agent
    from cucumber_agent.config import Config
    from cucumber_agent.session import Message, Role

    config = Config.load()
    agent = Agent.from_config(config)

    inventory = _planner_file_inventory(project_path)
    if spec_content:
        spec_preview = spec_content[:8000]
        spec_source_label = "SPEC.md / Projektbeschreibung"
    else:
        spec_preview = (
            "Keine SPEC.md vorhanden. Leite den Plan aus dem Projektinventar ab.\n"
            "Analysiere die vorhandenen Dateien und erstelle sinnvolle Aufgaben "
            "die das Projekt verbessern, vervollstaendigen oder stabilisieren."
        )
        spec_source_label = "Projektinventar (kein SPEC)"

    prompt = f"""Du bist der KI-Planner fuer Herbert Swarm.
Erstelle einen konkreten, aus dem Projekt abgeleiteten Multi-Agent-Plan.

Antworte AUSSCHLIESSLICH mit einem JSON-Objekt:
{{
  "phases": ["PHASE_NAME"],
  "tasks": [
    {{
      "id": "kurze-stabile-id",
      "description": "konkrete Aufgabe mit klarem Ergebnis",
      "agent_role": "coder|reviewer|tester|devops|designer|planner",
      "phase": "PHASE_NAME",
      "priority": 1,
      "files": ["relative/path.ext"],
      "dependencies": ["andere-kurze-stabile-id"]
    }}
  ],
  "reasoning": "kurze Begruendung"
}}

Regeln:
- Plane NUR, was aus der Projektbeschreibung und den Projektdateien wirklich folgt.
- Nutze sinnvolle Phasen in Ausfuehrungsreihenfolge — Phasen koennen frei benannt werden.
- Tasks muessen klein genug fuer einzelne Sub-Agenten sein und klare Dateipfade enthalten.
- Dateien muessen relative Pfade im Projekt sein. Keine absoluten Pfade, kein '..'.
- Dependencies duerfen nur auf task-ids aus deiner Antwort zeigen.
- Setze dependencies realistisch: spaetere Tasks auf fruehere, die ihre Ausgabe brauchen.
- Wenn die Anforderungen klein sind, reicht eine einzelne IMPLEMENTATION-Phase.
- Schreibe fuer jede task eine praezise description mit klarem Ergebnis (keine vagen Formulierungen).
- PFLICHT: Der Plan MUSS immer eine abschliessende Verifikations-Task enthalten (agent_role: "tester"
  oder "reviewer") die: alle erstellten Dateien prueft, vorhandene Tests ausfuehrt (npm test / pytest),
  Syntax-Fehler meldet und einen kurzen Testbericht in SWARM_REPORT.md schreibt.
- Bei Web-Projekten (package.json, HTML, Express, React): die Verifikations-Task prueft zusaetzlich
  ob `npm install` erfolgreich ist und alle JS/CSS-Dateien syntaktisch valide sind.

Projekt: {project_path.name}
Projektpfad: {project_path}
Quelle: {spec_source_label}

{spec_source_label}:
{spec_preview}

Projektinventar:
{json.dumps(inventory, ensure_ascii=False, indent=2)}"""

    response = await agent._provider.complete(
        messages=[Message(role=Role.USER, content=prompt)],
        model=config.agent.model,
        temperature=0.2,
        max_tokens=4000,
        tools=None,
    )
    return _extract_json_object(response.content)


# ---------------------------------------------------------------------------
# Improvement 1: Live Dashboard — _AgentState and _TaskLog
# ---------------------------------------------------------------------------


@dataclass
class _AgentState:
    tid: str
    role: str
    desc: str
    status: str = "waiting"  # waiting | running | done | failed
    step: int = 0
    max_steps: int = 30
    action: str = ""
    started_at: str = ""
    elapsed: float = 0.0


class _TaskLog:
    """Buffers console output for a task so Live display isn't disrupted."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def print(self, msg: str) -> None:
        self.lines.append(msg)

    def flush(self) -> None:
        for line in self.lines:
            console.print(line)
        self.lines.clear()


def _render_phase_table(
    agents: dict[str, _AgentState], phase_name: str, phase_num: int, total_phases: int
) -> Table:
    from rich import box as rbox

    table = Table(
        title=f"Phase {phase_num}/{total_phases}: {phase_name}",
        box=rbox.SIMPLE_HEAD,
        expand=True,
        title_style="bold cyan",
        show_header=True,
        header_style="bold dim",
    )
    table.add_column("Task", style="dim cyan", width=10)
    table.add_column("Rolle", width=10)
    table.add_column("Status", width=14)
    table.add_column("Fortschritt", width=16)
    table.add_column("Aktion", overflow="fold")

    _status_map = {
        "waiting": "[dim]o wartet[/dim]",
        "running": "[yellow]* laeuft[/yellow]",
        "done": "[green]v fertig[/green]",
        "failed": "[red]x fehler[/red]",
    }
    for tid, s in sorted(agents.items()):
        bar_len = 12
        filled = int((s.step / s.max_steps) * bar_len) if s.max_steps else 0
        bar = "#" * filled + "." * (bar_len - filled)
        step_str = f"{s.step}/{s.max_steps} [{bar}]"
        color = _ROLE_COLORS.get(s.role, "white")
        table.add_row(
            tid,
            f"[{color}]{s.role}[/{color}]",
            _status_map.get(s.status, s.status),
            f"[dim]{step_str}[/dim]",
            (s.action or s.desc)[:70],
        )
    return table


# ---------------------------------------------------------------------------
# Improvement 4: Plan-Critic (defined before _analyze_and_plan)
# ---------------------------------------------------------------------------


async def _llm_critic_plan(
    tasks: dict, phases: list[str], spec_content: str, project_path: Path
) -> list[dict]:
    """Ask the LLM to spot missing tasks in the plan. Returns list of new task dicts."""
    from cucumber_agent.agent import Agent
    from cucumber_agent.config import Config
    from cucumber_agent.session import Message as _Msg
    from cucumber_agent.session import Role as _Role

    config = Config.load()
    agent = Agent.from_config(config)

    task_summary = "\n".join(
        f"- {tid}: [{t['agent_role']}] Phase {t['phase']}: {t['description'][:90]}"
        for tid, t in tasks.items()
    )

    prompt = f"""Du bist der Critic-Agent fuer Herbert Swarm.
Pruefe den folgenden Plan auf fehlende, aber notwendige Aufgaben.

SPEC (Auszug):
{spec_content[:1500]}

AKTUELLER PLAN:
{task_summary}

PHASEN: {', '.join(phases)}

Antworte NUR mit einem JSON-Array. Leer [] wenn der Plan vollstaendig ist.
Sonst maximal 3 neue Tasks:
[
  {{
    "id": "critic-001",
    "description": "konkrete fehlende Aufgabe mit klarem Ergebnis",
    "agent_role": "tester|reviewer|coder|devops|designer",
    "phase": "{phases[-1] if phases else 'VERIFICATION'}",
    "priority": 10,
    "files": ["relative/path.ext"],
    "dependencies": [],
    "reason": "kurze Begruendung warum dieser Task fehlt"
  }}
]

Ergaenze NUR wenn WIRKLICH fehlend: .gitignore, Verifikationsskript, package.json scripts, README.
Keine Tasks die im Plan bereits vorhanden sind. Maximal 3."""

    try:
        response = await agent._provider.complete(
            messages=[_Msg(role=_Role.USER, content=prompt)],
            model=config.agent.model,
            temperature=0.1,
            max_tokens=800,
            tools=None,
        )
        content = (response.content or "").strip()
        if "```json" in content:
            content = content.split("```json", 1)[1].split("```", 1)[0]
        elif "```" in content:
            content = content.split("```", 1)[1].split("```", 1)[0]
        additions = json.loads(content.strip())
        if not isinstance(additions, list):
            return []
        return [t for t in additions if isinstance(t, dict) and t.get("description")]
    except Exception:
        return []


async def _analyze_and_plan(spec_content: str, project_path: Path) -> tuple[dict, list[str]]:
    """Analyze SPEC.md and create a task plan using the configured LLM."""
    try:
        plan = await _llm_create_task_plan(spec_content, project_path)
        if reasoning := str(plan.get("reasoning") or "").strip():
            console.print(f"  [dim]Planner: {reasoning[:160]}[/dim]")
        tasks, phases = _normalize_llm_plan(plan)

        # Plan-Critic pass: spot missing tasks
        console.print("  [dim]Critic prueft Plan auf Luecken...[/dim]")
        try:
            additions = await _llm_critic_plan(tasks, phases, spec_content, project_path)
            if additions:
                console.print(f"  [yellow]Critic ergaenzt {len(additions)} Task(s):[/yellow]")
                existing_count = len(tasks)
                for i, add in enumerate(additions[:3]):
                    critic_id = f"critic-{i + 1:03d}"  # noqa: F841
                    reason = add.get("reason", "")[:80]
                    desc = add.get("description", "")[:80]
                    role = add.get("agent_role", "reviewer")
                    if role not in _ALLOWED_AGENT_ROLES:
                        role = "reviewer"
                    console.print(f"    + [{role}] {desc}")
                    if reason:
                        console.print(f"      [dim]Grund: {reason}[/dim]")
                    # Determine phase number for the critic task (put in last phase)
                    phase_name = str(
                        add.get("phase") or (phases[-1] if phases else "VERIFICATION")
                    ).upper()
                    if phase_name not in phases:
                        phases.append(phase_name)
                    phase_num = phases.index(phase_name) + 1
                    task_id = f"task-{existing_count + i + 1:03d}"
                    tasks[task_id] = {
                        "id": task_id,
                        "description": desc,
                        "agent_role": role,
                        "files": _clean_task_files(add.get("files", [])),
                        "dependencies": [],
                        "status": "pending",
                        "priority": int(add.get("priority", 10)),
                        "phase": phase_num,
                        "created_by": "critic",
                    }
            else:
                console.print("  [dim]Critic: Plan vollstaendig[/dim]")
        except Exception as e:
            console.print(f"  [dim]Critic uebersprungen: {e}[/dim]")

        return tasks, phases
    except Exception as e:
        console.print(
            f"  [yellow]KI-Planung fehlgeschlagen: {e} — nutze neutralen Minimalplan[/yellow]"
        )
        return _generic_ai_unavailable_plan()


# ---------------------------------------------------------------------------
# Agent prompt builder
# ---------------------------------------------------------------------------


def _build_agent_prompt(task: dict, brain: dict, brain_file: Path) -> str:
    project_path = str(Path(brain.get("project_path", ".")).resolve())
    spec_summary = brain.get("spec_summary", "")
    tid = task["id"]
    files = "\n".join(f"  - {f}" for f in task["files"])
    spec_ctx = (
        f"\n### PROJEKT-SPEZIFIKATION (Zusammenfassung):\n{spec_summary[:1000]}\n"
        if spec_summary
        else ""
    )

    # Include results from completed dependency tasks so this agent can build on prior work.
    dep_ctx = ""
    facts = brain.get("facts", {})
    deps = task.get("dependencies", [])
    if deps and facts:
        dep_lines: list[str] = []
        for dep_id in deps:
            dep_fact = facts.get(f"task_{dep_id}_result")
            if dep_fact and isinstance(dep_fact, dict):
                summary = (dep_fact.get("summary") or "")[:350]
                created = dep_fact.get("files_created", [])
                if summary:
                    dep_lines.append(f"  [{dep_id}] {summary}")
                if created:
                    names = ", ".join(Path(f).name for f in created[:6])
                    dep_lines.append(f"  [{dep_id}] Dateien: {names}")
        if dep_lines:
            dep_ctx = "\n### ERGEBNISSE ABHAENGIGER AUFGABEN:\n" + "\n".join(dep_lines) + "\n"

    coding_standards = (
        "### CODING STANDARDS:\n"
        "- Schreibe sauberen, modularen und kommentierten Code.\n"
        "- Nutze moderne Best Practices fuer die jeweilige Sprache/Framework.\n"
        "- Vermeide Platzhalter (z.B. '// TODO') — implementiere die Logik vollstaendig.\n"
        "- Achte auf Fehlerbehandlung und Edge-Cases.\n"
    )

    brain_update = (
        f"\n### GEHIRN-UPDATE REGEL:\n"
        f"Nachdem du ALLE Dateien erstellt/bearbeitet hast, MUSST du das Projekt-Gehirn aktualisieren:\n"
        f"1. Lese die Datei: {brain_file}\n"
        f'2. Fuege dein Ergebnis zu brain["facts"]["task_{tid}_result"] hinzu.\n'
        f'3. Das Format MUSS ein JSON-Objekt sein: {{"files_created": [...], "summary": "<dein bericht>"}}\n'
    )

    return (
        f"Du bist ein spezialisierter {task['agent_role']} Agent im CucumberSwarm.\n"
        f"Dein Arbeitsverzeichnis ist: {project_path}\n\n"
        f"{spec_ctx}"
        f"{dep_ctx}\n"
        f"### DEINE AUFGABE ({tid}):\n"
        f"{task['description']}\n\n"
        f"### ZU ERSTELLENDE DATEIEN:\n"
        f"{files}\n\n"
        f"{coding_standards}\n"
        f"Arbeite Schritt fuer Schritt. Nutze 'shell' oder 'write_file' fuer deine Arbeit.\n"
        f"{brain_update}"
    )


# ---------------------------------------------------------------------------
# Sub-agent execution
# ---------------------------------------------------------------------------


def _format_failure(
    message: str,
    *,
    error_type: str = "SwarmTaskError",
    tool_name: str | None = None,
    args: dict | None = None,
    output: str = "",
) -> dict:
    clean_message = (message or "").strip() or "Tool failed without stderr/output"
    failure = {
        "success": False,
        "output": clean_message[:800],
        "error_type": error_type,
        "message": clean_message[:800],
    }
    if tool_name:
        failure["tool_name"] = tool_name
    if args:
        failure["args"] = {
            key: (str(value)[:160] + ("..." if len(str(value)) > 160 else ""))
            for key, value in args.items()
        }
    if output.strip():
        failure["tool_output"] = output.strip()[:800]
    return failure


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _summarize_tool_args(tool_name: str, args: dict) -> str:
    """Return a compact one-line preview of the most relevant tool arguments."""
    if not args:
        return ""
    preview_parts = []
    if tool_name == "shell":
        cmd = str(args.get("command", ""))[:60]
        preview_parts.append(cmd)
    elif tool_name in ("write_file", "read_file", "patch"):
        path = str(args.get("path", ""))
        preview_parts.append(path)
    elif tool_name == "browser_navigate":
        url = str(args.get("url", ""))[:50]
        preview_parts.append(url)
    elif tool_name == "search_files":
        pattern = str(args.get("pattern", ""))[:30]
        preview_parts.append(f"pattern={pattern}")
    elif tool_name == "delegate_task":
        goal = str(args.get("goal", ""))[:50]
        preview_parts.append(f"goal={goal}")
    elif tool_name == "terminal":
        cmd = str(args.get("command", ""))[:60]
        preview_parts.append(cmd)
    # Skip all positional parameters of every known tool to avoid
    # "multiple values for" collisions when ToolRegistry.execute(name, **kwargs)
    # forwards to tool.execute(pos_arg=value, **kwargs)
    skip_keys = {
        "name",
        "code",
        "task",
        "prompt",
        "image_url",
        "path",
        "url",
        "command",
        "pattern",
        "goal",
        "session",
        "target",
        "query",
        "working_dir",
        # SwarmTool positional params
        "project",
        "spec",
        "parallel",
        "timeout",
        "dry_run",
        "retry_failed",
        "yes",
    }
    for k, v in args.items():
        if k in skip_keys:
            continue
        preview_parts.append(f"{k}={v}"[:40])
        break
    return " | ".join(preview_parts)


def _project_relative_path(path_value: str, project_path: Path) -> Path:
    candidate = Path(path_value).expanduser()
    if not candidate.is_absolute():
        candidate = project_path / candidate
    return candidate.resolve()


def _normalize_swarm_tool_args(
    tool_name: str,
    args: dict,
    project_path: Path,
) -> tuple[dict | None, dict | None]:
    normalized = dict(args)

    if tool_name == "shell":
        normalized.setdefault("working_dir", str(project_path))
        return normalized, None

    if tool_name in {"write_file", "read_file"} and "path" in normalized:
        target = _project_relative_path(str(normalized["path"]), project_path)
        if not _is_inside(target, project_path):
            return None, _format_failure(
                f"{tool_name} path outside project blocked: {target}",
                error_type="PathSafetyError",
                tool_name=tool_name,
                args=args,
            )
        normalized["path"] = str(target)

    return normalized, None


async def _run_task_async(
    tid: str,
    task: dict,
    brain: dict,
    brain_file: Path,
    agent_state: _AgentState | None = None,
    task_log: _TaskLog | None = None,
) -> dict:
    from cucumber_agent.agent import Agent
    from cucumber_agent.config import Config
    from cucumber_agent.session import Session

    config = Config.load()
    agent = Agent.from_config(config)
    session = Session(id=f"swarm-{tid}", model=config.agent.model)
    project_path = Path(brain.get("project_path", ".")).resolve()

    # Sub-agents in swarm context are expected to run without interaction.
    # We manually execute tools here, which implicitly skip approval.

    prompt = _build_agent_prompt(task, brain, brain_file)

    def _log(msg: str) -> None:
        if task_log is not None:
            task_log.print(msg)
        else:
            console.print(msg)

    try:
        current_input = prompt
        max_steps = 30
        import time as _time

        if agent_state is not None:
            agent_state.max_steps = max_steps

        # Show task header with agent role (only when not using Live dashboard)
        role = task.get("agent_role", "?")
        role_color = _ROLE_COLORS.get(role, "white")
        if agent_state is None:
            console.print(
                f"\n  [bold cyan]> {tid}[/bold cyan] "
                f"[bold {role_color}][{role}][/bold {role_color}] "
                f"[dim]{task['description'][:80]}[/dim]"
            )
            console.print(f"  [dim]    Gestartet: {datetime.now().strftime('%H:%M:%S')}[/dim]")

        for step in range(max_steps):
            step_start = _time.monotonic()

            if agent_state is not None:
                agent_state.step = step
                agent_state.action = f"Schritt {step + 1}/{max_steps} — Denke..."
            else:
                # Progress: step indicator
                bar_len = 12
                filled = int((step / max_steps) * bar_len)
                bar = "#" * filled + "." * (bar_len - filled)
                _log(
                    f"  [dim cyan][{tid}][/dim cyan] [{step + 1}/{max_steps}] [dim]{bar}[/dim] Denke... "
                )

            response = await agent.run_with_tools(session, current_input)
            step_duration = _time.monotonic() - step_start

            if step_duration > 60:
                _log(
                    f"  [dim cyan][{tid}][/dim cyan]   [yellow]LLM: {step_duration:.0f}s[/yellow]"
                )

            # Show agent thought / reasoning before tools
            if response.content and not response.tool_calls:
                thought = response.content[:300].replace("\n", " ").strip()
                if agent_state is not None:
                    agent_state.action = thought[:70]
                else:
                    _log(f"  [dim cyan][{tid}][/dim cyan]   [dim]{thought}[/dim]")

            if not response.tool_calls:
                output_preview = (response.content or "")[:200].replace("\n", " ").strip()
                if agent_state is not None:
                    agent_state.step = max_steps
                    agent_state.action = "Abgeschlossen"
                else:
                    _log(
                        f"  [dim cyan][{tid}][/dim cyan]   [green]Abgeschlossen[/green] [dim]{output_preview}[/dim]"
                    )
                return {"success": True, "output": (response.content or "")[:600]}

            # Execute each tool call
            for tc in response.tool_calls:
                # Show tool call with key args
                args_preview = _summarize_tool_args(tc.name, tc.arguments)
                if agent_state is not None:
                    agent_state.action = f"{tc.name} {args_preview}"[:70]
                else:
                    _log(
                        f"  [dim cyan][{tid}][/dim cyan]   [cyan]-> {tc.name}[/cyan] [dim]{args_preview}[/dim]"
                    )

                tool_args, blocked = _normalize_swarm_tool_args(
                    tc.name,
                    tc.arguments,
                    project_path,
                )
                if blocked is not None:
                    return blocked

                try:
                    result = await ToolRegistry.execute(tc.name, **(tool_args or {}))
                except Exception as e:
                    return _format_failure(str(e), tool_name=tc.name, args=tc.arguments)

                output_text = (
                    result.output if result.success else "ERROR: " + (result.error or result.output)
                )
                if len(output_text) > 4000:
                    output_text = (
                        output_text[:2000] + "\n... [TRUNCATED] ...\n" + output_text[-2000:]
                    )

                if not result.success and not output_text.strip():
                    output_text = "ERROR: Tool failed without stderr/output"

                # Show first line of result
                first_line = output_text.split("\n")[0][:120].replace("\n", " ").strip()
                status_icon = "[green]v[/green]" if result.success else "[red]x[/red]"
                _log(f"  [dim cyan][{tid}][/dim cyan]     {status_icon} {first_line}")

                session.messages.append(
                    Message(
                        role=Role.TOOL,
                        content=output_text,
                        name=tc.name,
                        tool_call_id=tc.id,
                    )
                )

            # If the agent used tools, inject a neutral continuation prompt.
            current_input = (
                "[ Weiter mit dem naechsten Schritt — die vorherigen Tools wurden ausgefuehrt. ]"
            )

        if agent_state is not None:
            agent_state.action = f"Step-Limit ({max_steps}) erreicht"
        else:
            _log(
                f"  [dim cyan][{tid}][/dim cyan]   [yellow]Step-Limit ({max_steps}) erreicht[/yellow]"
            )
        return {"success": False, "output": "Step limit reached before task completion"}
    except Exception as e:
        logger.exception(f"Exception in swarm task {tid}")
        return _format_failure(str(e), error_type=type(e).__name__)


def _task_error_summary(result: dict) -> str:
    message = str(result.get("message") or result.get("output") or "").strip()
    if not message:
        message = "Tool failed without stderr/output"

    error_type = str(result.get("error_type") or "").strip()
    tool_name = str(result.get("tool_name") or "").strip()
    prefix_parts = []
    if error_type:
        prefix_parts.append(error_type)
    if tool_name:
        prefix_parts.append(f"tool={tool_name}")

    prefix = f"{' | '.join(prefix_parts)}: " if prefix_parts else ""
    return f"{prefix}{message}"


# ---------------------------------------------------------------------------
# Improvement 2: Real Verification Phase
# ---------------------------------------------------------------------------


async def _run_verification(project_path: Path, brain: dict) -> dict:
    """Run hard checks on the built project. Returns {passed, failed, warnings}."""
    results: dict[str, list[str]] = {"passed": [], "failed": [], "warnings": []}

    def run_cmd(cmd: list[str], cwd: Path, timeout: int = 90) -> tuple[bool, str]:
        try:
            r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
            out = (r.stdout + "\n" + r.stderr).strip()
            return r.returncode == 0, out[:400]
        except subprocess.TimeoutExpired:
            return False, f"Timeout after {timeout}s"
        except FileNotFoundError:
            return False, f"Not found: {cmd[0]}"
        except Exception as e:
            return False, str(e)[:200]

    tasks = brain.get("tasks", {})

    # 1. Check all planned files exist and are non-empty
    stub_markers = [
        "# TODO",
        "// TODO",
        "# FIXME",
        "// FIXME",
        "raise NotImplementedError",
        'throw new Error("TODO',
    ]
    for tid, task in tasks.items():
        for fp in task.get("files", []):
            full = project_path / fp
            if not full.exists():
                results["failed"].append(f"Datei fehlt: {fp} ({tid})")
                continue
            try:
                content = full.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if not content.strip():
                results["warnings"].append(f"Leere Datei: {fp}")
            else:
                found = [m for m in stub_markers if m in content]
                if found:
                    results["warnings"].append(f"Stub in {fp}: {', '.join(found[:2])}")

    # 2. Node.js project checks
    if (project_path / "package.json").exists():
        ok, out = run_cmd(["npm", "install", "--prefer-offline"], project_path, timeout=120)
        if ok:
            results["passed"].append("npm install")
        else:
            results["failed"].append(f"npm install: {out[:150]}")

        # JS syntax check
        for js_file in sorted(project_path.rglob("*.js")):
            if any(p in js_file.parts for p in ("node_modules", "dist", "build")):
                continue
            ok, out = run_cmd(["node", "--check", str(js_file)], project_path, timeout=10)
            rel = str(js_file.relative_to(project_path))
            if ok:
                results["passed"].append(f"JS syntax OK: {rel}")
            else:
                results["failed"].append(f"JS Syntaxfehler in {rel}: {out[:120]}")

        # npm test if available
        try:
            pkg_data = json.loads((project_path / "package.json").read_text())
            if "test" in pkg_data.get("scripts", {}):
                ok, out = run_cmd(["npm", "test"], project_path, timeout=60)
                if ok:
                    results["passed"].append("npm test")
                else:
                    results["warnings"].append(f"npm test: {out[:150]}")
        except (json.JSONDecodeError, OSError):
            pass

    # 3. Python project checks
    if (project_path / "pyproject.toml").exists() or (project_path / "requirements.txt").exists():
        for py_file in sorted(project_path.rglob("*.py")):
            if any(p in py_file.parts for p in (".venv", "__pycache__", "dist", "build")):
                continue
            ok, out = run_cmd(["python3", "-m", "py_compile", str(py_file)], project_path, timeout=10)
            rel = str(py_file.relative_to(project_path))
            if ok:
                results["passed"].append(f"Python syntax OK: {rel}")
            else:
                results["failed"].append(f"Python Syntaxfehler in {rel}: {out[:120]}")

        # pytest if available
        ok, out = run_cmd(["python3", "-m", "pytest", "--tb=short", "-q"], project_path, timeout=60)
        if ok:
            results["passed"].append("pytest")
        else:
            results["warnings"].append(f"pytest: {out[:150]}")

    return results


def _print_verification_results(results: dict) -> None:
    for check in results.get("passed", []):
        console.print(f"  [green]v[/green] {check}")
    for check in results.get("warnings", []):
        console.print(f"  [yellow]![/yellow] {check}")
    for check in results.get("failed", []):
        console.print(f"  [red]x[/red] {check}")


def _write_swarm_report(project_path: Path, brain: dict, verification: dict) -> None:
    """Write SWARM_REPORT.md with verification results and task summary."""
    tasks = brain.get("tasks", {})
    passed = verification.get("passed", [])
    failed = verification.get("failed", [])
    warnings = verification.get("warnings", [])

    lines = [
        f"# Swarm Report: {brain.get('project_name', '?')}",
        "",
        f"Erstellt: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## Verifikation",
        "",
        "| Status | Anzahl |",
        "|--------|--------|",
        f"| v Passed | {len(passed)} |",
        f"| ! Warnings | {len(warnings)} |",
        f"| x Failed | {len(failed)} |",
        "",
    ]
    if failed:
        lines += ["### Fehler", ""] + [f"- x {f}" for f in failed] + [""]
    if warnings:
        lines += ["### Warnungen", ""] + [f"- ! {w}" for w in warnings] + [""]
    if passed:
        lines += ["### Bestanden", ""] + [f"- v {p}" for p in passed[:20]] + [""]

    done = sum(1 for t in tasks.values() if t["status"] == "done")
    total = len(tasks)
    lines += [
        "## Aufgaben",
        "",
        f"**{done}/{total} Tasks abgeschlossen**",
        "",
    ]
    for tid, task in sorted(tasks.items()):
        icon = "v" if task["status"] == "done" else "x" if task["status"] == "failed" else "o"
        lines.append(
            f"- {icon} `{tid}` [{task['agent_role']}] {task['description'][:80]}"
        )

    try:
        (project_path / "SWARM_REPORT.md").write_text("\n".join(lines), encoding="utf-8")
        console.print("  [dim]-> SWARM_REPORT.md geschrieben[/dim]")
    except OSError as e:
        console.print(f"  [yellow]! SWARM_REPORT.md konnte nicht geschrieben werden: {e}[/yellow]")


# ---------------------------------------------------------------------------
# Improvement 3: Auto-Fix Loop
# ---------------------------------------------------------------------------


async def _run_auto_fix_loop(
    project_path: Path,
    brain: dict,
    brain_file: Path,
    semaphore: asyncio.Semaphore,
    timeout: int,
    max_iterations: int = 2,
) -> dict:
    """Verify -> fix -> verify cycle. Returns final verification results."""
    for iteration in range(1, max_iterations + 1):
        console.print(
            f"\n[bold cyan]Verifikation — Runde {iteration}/{max_iterations}[/bold cyan]"
        )
        vresults = await _run_verification(project_path, brain)
        _print_verification_results(vresults)

        if not vresults["failed"]:
            console.print("  [green]Alle Checks bestanden[/green]")
            _write_swarm_report(project_path, brain, vresults)
            return vresults

        if iteration == max_iterations:
            console.print(
                f"  [red]{len(vresults['failed'])} Fehler verbleiben nach {max_iterations} Runden[/red]"
            )
            _write_swarm_report(project_path, brain, vresults)
            return vresults

        # Build one combined fix prompt with all failures
        failures_text = "\n".join(f"- {f}" for f in vresults["failed"][:8])
        warnings_text = "\n".join(f"- {w}" for w in vresults["warnings"][:4])
        fix_tid = f"fix-r{iteration}"
        fix_task = {
            "id": fix_tid,
            "description": f"Auto-Fix Runde {iteration}: Behebe Verifikationsfehler",
            "agent_role": "coder",
            "files": [],
            "dependencies": [],
            "status": "pending",
            "priority": 99,
            "phase": 99,
            "created_by": "auto-fix",
        }
        brain["tasks"][fix_tid] = fix_task
        await _save_brain(brain, brain_file)

        console.print(
            f"\n  [yellow]-> Starte Auto-Fix Agent fuer {len(vresults['failed'])} Fehler...[/yellow]"
        )

        # Build a targeted fix prompt
        fix_prompt = (
            f"Du bist ein Fixer-Agent fuer das Projekt '{brain.get('project_name', '?')}'.\n"
            f"Arbeitsverzeichnis: {project_path}\n\n"
            f"Die automatische Verifikation hat folgende FEHLER gefunden:\n{failures_text}\n\n"
            f"Warnungen (falls Zeit):\n{warnings_text}\n\n"
            f"Behebe ALLE Fehler vollstaendig. Nutze shell und write_file. "
            f"Pruefe nach jedem Fix ob er wirklich funktioniert. "
            f"Fasse am Ende kurz zusammen was du behoben hast."
        )

        fix_task_data = dict(fix_task)
        fix_task_data["description"] = fix_prompt[:400]

        try:
            fix_result = await asyncio.wait_for(
                _run_task_async(fix_tid, fix_task_data, brain, brain_file),
                timeout=timeout,
            )
            ok = fix_result.get("success", False)
            brain["tasks"][fix_tid]["status"] = "done" if ok else "failed"
            brain["tasks"][fix_tid]["completed_at"] = datetime.now().isoformat()
            if ok:
                console.print("  [green]Fix Agent fertig[/green]")
            else:
                console.print(
                    f"  [red]Fix Agent fehlgeschlagen: {_task_error_summary(fix_result)[:100]}[/red]"
                )
        except Exception as e:
            brain["tasks"][fix_tid]["status"] = "failed"
            console.print(f"  [red]Fix Agent Exception: {e}[/red]")

        await _save_brain(brain, brain_file)

    return await _run_verification(project_path, brain)


# ---------------------------------------------------------------------------
# Improvement 5: Per-Task Quality Gate (defined before _cmd_run)
# ---------------------------------------------------------------------------


def _check_task_quality(task: dict, project_path: Path) -> list[str]:
    """Check that a task's promised files exist and aren't empty/stub-only."""
    issues: list[str] = []
    stub_markers = [
        "# TODO",
        "// TODO",
        "# FIXME",
        "// FIXME",
        "raise NotImplementedError()",
        'throw new Error("TODO',
    ]
    for fp in task.get("files", []):
        full = project_path / fp
        if not full.exists():
            issues.append(f"Datei nicht erstellt: {fp}")
            continue
        try:
            content = full.read_text(encoding="utf-8", errors="ignore").strip()
        except OSError:
            continue
        if not content:
            issues.append(f"Datei leer: {fp}")
            continue
        found = [m for m in stub_markers if m in content]
        if len(found) >= 3:  # Only fail on many stubs, not one
            issues.append(f"Zu viele Stubs in {fp}: {', '.join(found[:2])}")
    return issues


# ---------------------------------------------------------------------------
# Command implementations
# ---------------------------------------------------------------------------


async def _cmd_init(project: str, name: str | None = None) -> str:
    project_path = Path(project).resolve()
    project_name = name or project_path.name
    brain_file = _brain_file_for(project_path)

    project_path.mkdir(parents=True, exist_ok=True)
    brain: dict = {
        "project_name": project_name,
        "project_path": str(project_path),
        "spec_summary": "",
        "facts": {},
        "files": {},
        "tasks": {},
        "phases": [],
        "created_at": datetime.now().isoformat(),
        "current_phase": 0,
    }
    await _save_brain(brain, brain_file)

    console.print(
        Panel(
            f"[bold green]Swarm initialized[/bold green]\n"
            f"[bold]Project:[/bold] {project_name}\n"
            f"[bold]Path:[/bold]    {project_path}\n"
            f"[bold]Brain:[/bold]   {brain_file}\n\n"
            f"[bold cyan]-> Naechster Schritt:[/bold cyan] /herbert-swarm plan {project_path}",
            title="[bold cyan]CucumberSwarm[/bold cyan]",
            border_style="cyan",
        )
    )
    return f"Swarm initialized for '{project_name}' at {project_path}. Brain: {brain_file}"


async def _cmd_plan(project: str, spec: str | None = None) -> str:
    project_path = Path(project).resolve()
    brain_file = _brain_file_for(project_path)
    brain = await _load_brain(brain_file)
    if brain is None:
        return f"ERROR: No swarm brain at {brain_file}. Run 'init' first."

    spec_path = Path(spec).resolve() if spec else project_path / "SPEC.md"
    if spec_path.exists():
        spec_content = spec_path.read_text(encoding="utf-8")
        brain["spec_summary"] = spec_content[:2000]
    else:
        # Fall back to README and other context documents.
        fallback_parts: list[str] = []
        for fname in ("README.md", "README.txt", "TODO.md", "GOAL.md"):
            fpath = project_path / fname
            if fpath.exists():
                try:
                    text = fpath.read_text(encoding="utf-8", errors="ignore")[:2000]
                    fallback_parts.append(f"# {fname}\n{text}")
                except OSError:
                    pass
        spec_content = "\n\n".join(fallback_parts)
        if spec_content:
            console.print("[yellow]No SPEC.md — using README/docs as project context[/yellow]")
            brain["spec_summary"] = spec_content[:2000]
        else:
            console.print(
                f"[yellow]No spec or README at {spec_path} — planning from file inventory only[/yellow]"
            )

    tasks, phases = await _analyze_and_plan(spec_content, project_path)
    brain["tasks"] = tasks
    brain["phases"] = phases
    await _save_brain(brain, brain_file)

    lines = [f"[bold]Plan erstellt:[/bold] {len(tasks)} Tasks in {len(phases)} Phasen\n"]
    for i, phase_name in enumerate(phases, 1):
        phase_tasks = [t for t in tasks.values() if t["phase"] == i]
        lines.append(f"  Phase {i}: [cyan]{phase_name}[/cyan] ({len(phase_tasks)} tasks)")

    next_hint = (
        f"\n[bold cyan]-> Naechster Schritt:[/bold cyan] /herbert-swarm run {project_path}"
        if tasks
        else ""
    )

    console.print(
        Panel(
            "\n".join(lines) + next_hint,
            title="[bold cyan]CucumberSwarm — Plan[/bold cyan]",
            border_style="cyan",
        )
    )
    return f"Plan: {len(tasks)} tasks across {len(phases)} phases ({', '.join(phases)})"


async def _cmd_run(
    project: str,
    parallel: int = 3,
    timeout: int = 600,
    dry_run: bool = False,
    retry_failed: bool = False,
) -> str:
    if parallel < 1:
        return "ERROR: parallel must be at least 1."
    if timeout < 1:
        return "ERROR: timeout must be at least 1 second."

    project_path = Path(project).resolve()
    brain_file = _brain_file_for(project_path)
    brain = await _load_brain(brain_file)
    if brain is None:
        return f"ERROR: No swarm brain at {brain_file}. Run 'init' and 'plan' first."
    if not brain.get("tasks"):
        return "ERROR: No tasks in plan. Run 'plan' first."

    if retry_failed:
        retried = 0
        for task in brain["tasks"].values():
            if task["status"] == "failed":
                task["status"] = "pending"
                task.pop("error", None)
                task.pop("completed_at", None)
                retried += 1
        if retried == 0:
            return "No failed tasks to retry."
        console.print(f"[yellow]Retrying {retried} failed task(s)...[/yellow]")
        await _save_brain(brain, brain_file)

    run_start = datetime.now()
    console.print(
        Panel(
            f"[bold]Project:[/bold]  {brain['project_name']}\n"
            f"[bold]Tasks:[/bold]    {len(brain['tasks'])}\n"
            f"[bold]Phases:[/bold]   {', '.join(brain.get('phases', []))}\n"
            f"[bold]Parallel:[/bold] {parallel}  [bold]Timeout:[/bold] {timeout}s/agent"
            + ("\n[yellow]DRY RUN — no agents called[/yellow]" if dry_run else ""),
            title="[bold cyan]CucumberSwarm — Execution[/bold cyan]",
            border_style="cyan",
        )
    )

    semaphore = asyncio.Semaphore(parallel)
    total_phases = len(brain.get("phases", []))

    for phase_num, phase_name in enumerate(brain.get("phases", []), 1):
        phase_tasks = [
            (tid, t)
            for tid, t in brain["tasks"].items()
            if t["phase"] == phase_num and t["status"] == "pending"
        ]
        if not phase_tasks:
            continue

        console.print(
            f"\n[bold cyan]=== Phase {phase_num}: {phase_name} ===[/bold cyan] "
            f"[dim]({len(phase_tasks)} tasks, max {parallel} parallel)[/dim]"
        )

        for tid, task in phase_tasks:
            task["status"] = "running"
            task["started_at"] = datetime.now().isoformat()
        await _save_brain(brain, brain_file)

        if dry_run:
            for tid, task in phase_tasks:
                task["status"] = "done"
                task["completed_at"] = datetime.now().isoformat()
                console.print(
                    f"  [yellow][DRY][/yellow] [cyan]{tid}[/cyan]: {task['description'][:55]}"
                )
        else:
            # --- Improvement 1: Live Dashboard ---
            agents: dict[str, _AgentState] = {}
            task_logs: dict[str, _TaskLog] = {}

            for tid, task in phase_tasks:
                agents[tid] = _AgentState(
                    tid=tid,
                    role=task.get("agent_role", "?"),
                    desc=task.get("description", "")[:70],
                    started_at=datetime.now().strftime("%H:%M:%S"),
                )
                task_logs[tid] = _TaskLog()

            import inspect as _inspect

            _run_task_fn = _run_task_async
            _task_fn_supports_state = "agent_state" in _inspect.signature(_run_task_fn).parameters

            async def run_one(tid: str, task: dict) -> tuple[str, dict]:
                async with semaphore:
                    agent_state = agents[tid]
                    task_log = task_logs[tid]
                    agent_state.status = "running"
                    agent_state.started_at = datetime.now().strftime("%H:%M:%S")
                    t0 = asyncio.get_event_loop().time()
                    try:
                        if _task_fn_supports_state:
                            coro = _run_task_fn(
                                tid,
                                task,
                                brain,
                                brain_file,
                                agent_state=agent_state,
                                task_log=task_log,
                            )
                        else:
                            coro = _run_task_fn(tid, task, brain, brain_file)
                        result = await asyncio.wait_for(coro, timeout=timeout)
                    except TimeoutError:
                        result = _format_failure(
                            f"Timed out after {timeout}s", error_type="TimeoutError"
                        )
                    except Exception as exc:
                        result = _format_failure(str(exc), error_type=type(exc).__name__)

                    agent_state.elapsed = asyncio.get_event_loop().time() - t0
                    ok = result.get("success", False)

                    # --- Improvement 5: Quality Gate ---
                    if ok:
                        quality_issues = _check_task_quality(task, project_path)
                        if quality_issues:
                            issue_text = "; ".join(quality_issues[:3])
                            task_log.print(
                                f"  [yellow]Quality-Gate [{tid}]: {issue_text}[/yellow]"
                            )
                            result = _format_failure(
                                f"Quality gate: {issue_text}", error_type="QualityGateError"
                            )
                            ok = False

                    agent_state.status = "done" if ok else "failed"
                    agent_state.action = (
                        "Fertig" if ok else f"Fehler: {_task_error_summary(result)[:50]}"
                    )
                    return tid, result

            with Live(
                _render_phase_table(agents, phase_name, phase_num, total_phases),
                console=console,
                refresh_per_second=2,
                transient=False,
            ) as live:

                async def _refresher() -> None:
                    while True:
                        await asyncio.sleep(0.5)
                        live.update(
                            _render_phase_table(agents, phase_name, phase_num, total_phases)
                        )

                refresher_task = asyncio.create_task(_refresher())
                result_pairs = await asyncio.gather(
                    *(run_one(tid, task) for tid, task in phase_tasks)
                )
                refresher_task.cancel()
                try:
                    await refresher_task
                except asyncio.CancelledError:
                    pass
                live.update(_render_phase_table(agents, phase_name, phase_num, total_phases))

            results = dict(result_pairs)

            # Flush detail logs after Live ends
            for tid, _ in phase_tasks:
                task_logs[tid].flush()

            for tid, task in phase_tasks:
                r = results.get(tid, {})
                if r.get("success"):
                    task["status"] = "done"
                    task.pop("error", None)
                    abs_files = [
                        str((project_path / file_path).resolve())
                        for file_path in task.get("files", [])
                        if (project_path / file_path).exists()
                    ]
                    brain.setdefault("facts", {})[f"task_{tid}_result"] = {
                        "files_created": abs_files,
                        "summary": r.get("output", "")[:300],
                    }
                else:
                    task["status"] = "failed"
                    task["error"] = _task_error_summary(r)[:500]
                    task["error_details"] = {
                        key: value for key, value in r.items() if key not in {"success"}
                    }
                task["completed_at"] = datetime.now().isoformat()

        # Phase summary after all tasks in this phase finish
        phase_done = sum(1 for t in phase_tasks if brain["tasks"][t[0]]["status"] == "done")
        phase_failed = sum(1 for t in phase_tasks if brain["tasks"][t[0]]["status"] == "failed")
        icon = "[green]v[/green]" if not phase_failed else f"[red]! {phase_failed} failed[/red]"
        console.print(
            f"  [dim]Phase {phase_num} abgeschlossen:[/dim] {icon} {phase_done}/{len(phase_tasks)} done\n"
        )

        await _save_brain(brain, brain_file)
        brain["current_phase"] = phase_num
        await _save_brain(brain, brain_file)

    # --- Integration: Verification + Auto-Fix after all phases ---
    if not dry_run:
        console.print("\n[bold cyan]=== Verifikation & Auto-Fix ===[/bold cyan]")
        final_verification = await _run_auto_fix_loop(
            project_path, brain, brain_file, semaphore, timeout, max_iterations=2
        )
        brain["verification"] = final_verification
        await _save_brain(brain, brain_file)

    done = sum(1 for t in brain["tasks"].values() if t["status"] == "done")
    failed = sum(1 for t in brain["tasks"].values() if t["status"] == "failed")
    total = len(brain["tasks"])
    elapsed = int((datetime.now() - run_start).total_seconds())

    summary_table = Table.grid(padding=(0, 2))
    summary_table.add_row("[bold]Done:[/bold]", f"[green]{done}/{total}[/green]")
    summary_table.add_row("[bold]Failed:[/bold]", f"[red]{failed}[/red]" if failed else "0")
    summary_table.add_row("[bold]Elapsed:[/bold]", f"{elapsed}s")
    console.print(
        Panel(
            summary_table,
            title="[bold cyan]CucumberSwarm — Complete[/bold cyan]",
            border_style="cyan",
        )
    )

    suffix = f" ({failed} failed — run 'swarm run --retry-failed' to retry)" if failed else ""
    return f"Swarm complete: {done}/{total} tasks done{suffix}"


async def _cmd_status(project: str | None) -> str:
    brain_file = _brain_file_for(project)
    brain = await _load_brain(brain_file)
    if brain is None:
        return f"No brain found at {brain_file}. Run 'init' first."

    tasks = brain.get("tasks", {})
    if not tasks:
        return "No tasks — run 'plan' first."

    by_status: dict[str, int] = {}
    for t in tasks.values():
        by_status[t["status"]] = by_status.get(t["status"], 0) + 1

    lines = [
        f"[bold]Project:[/bold] {brain.get('project_name', '?')}  "
        f"[bold]Tasks:[/bold] {len(tasks)}\n"
    ]
    icons = {"pending": "o", "running": "~", "done": "*", "failed": "x"}
    for status, count in sorted(by_status.items()):
        icon = icons.get(status, "?")
        color = {"done": "green", "failed": "red", "running": "yellow"}.get(status, "dim")
        lines.append(f"  [{color}]{icon} {status}:[/{color}] {count}")

    for phase_num, phase_name in enumerate(brain.get("phases", []), 1):
        phase_tasks = [t for t in tasks.values() if t["phase"] == phase_num]
        done = sum(1 for t in phase_tasks if t["status"] == "done")
        failed = sum(1 for t in phase_tasks if t["status"] == "failed")
        bar = "*" * done + "x" * failed + "o" * (len(phase_tasks) - done - failed)
        lines.append(
            f"\n  Phase {phase_num} [cyan]{phase_name}[/cyan]: [{bar}] {done}/{len(phase_tasks)}"
        )

    console.print(
        Panel(
            "\n".join(lines),
            title="[bold cyan]CucumberSwarm — Status[/bold cyan]",
            border_style="cyan",
        )
    )

    parts = [f"{s}: {c}" for s, c in sorted(by_status.items())]
    return f"Status for '{brain.get('project_name', '?')}': " + ", ".join(parts)


async def _cmd_report(project: str | None) -> str:
    brain_file = _brain_file_for(project)
    brain = await _load_brain(brain_file)
    if brain is None:
        return f"No brain at {brain_file}. Run 'init' first."

    tasks = brain.get("tasks", {})
    facts = brain.get("facts", {})

    total = len(tasks)
    done = sum(1 for t in tasks.values() if t["status"] == "done")
    failed = sum(1 for t in tasks.values() if t["status"] == "failed")
    pending = sum(1 for t in tasks.values() if t["status"] == "pending")
    pct = f"{done / total * 100:.0f}%" if total else "0%"

    all_files: list[str] = []
    for tid, task in tasks.items():
        fact = facts.get(f"task_{tid}_result", {})
        if isinstance(fact, dict):
            for f in fact.get("files_created", []):
                if f not in all_files:
                    all_files.append(f)

    report_table = Table.grid(padding=(0, 2))
    report_table.add_row("[bold]Project:[/bold]", brain.get("project_name", "?"))
    report_table.add_row("[bold]Done:[/bold]", f"[green]{done}/{total}[/green] ({pct})")
    if failed:
        report_table.add_row("[bold]Failed:[/bold]", f"[red]{failed}[/red]")
    if pending:
        report_table.add_row("[bold]Pending:[/bold]", str(pending))
    if all_files:
        report_table.add_row("[bold]Files:[/bold]", str(len(all_files)))

    console.print(
        Panel(
            report_table,
            title="[bold cyan]CucumberSwarm — Report[/bold cyan]",
            border_style="cyan",
        )
    )

    if all_files:
        for f in all_files[:20]:
            exists = Path(f).exists()
            console.print(f"  {'[green]v[/green]' if exists else '[yellow]?[/yellow]'} {f}")

    if failed:
        for tid, task in tasks.items():
            if task["status"] == "failed":
                error = task.get("error", "") or "Tool failed without stderr/output"
                console.print(f"  [red]x[/red] {tid}: {error[:220]}")
                details = task.get("error_details", {})
                if isinstance(details, dict):
                    tool_name = details.get("tool_name")
                    error_type = details.get("error_type")
                    if tool_name or error_type:
                        console.print(
                            "    [dim]"
                            + " | ".join(str(v) for v in (error_type, tool_name) if v)
                            + "[/dim]"
                        )
        console.print("  [dim]Retry: /herbert-swarm run --retry-failed[/dim]")

    return f"Report: {done}/{total} done ({pct}), {len(all_files)} files created"


async def _cmd_brain(project: str | None) -> str:
    brain_file = _brain_file_for(project)
    brain = await _load_brain(brain_file)
    if brain is None:
        return f"No brain at {brain_file}. Run 'init' first."

    tasks = brain.get("tasks", {})
    facts = brain.get("facts", {})

    lines = [
        f"[bold]Project:[/bold]  {brain.get('project_name', '?')}",
        f"[bold]Path:[/bold]     {brain.get('project_path', '?')}",
        f"[bold]Created:[/bold]  {brain.get('created_at', '?')}",
        f"[bold]Phase:[/bold]    {brain.get('current_phase', 0)} / {len(brain.get('phases', []))}",
        f"[bold]Tasks:[/bold]    {len(tasks)}  [bold]Facts:[/bold] {len(facts)}",
    ]
    console.print(
        Panel(
            "\n".join(lines),
            title="[bold cyan]CucumberSwarm — Brain[/bold cyan]",
            border_style="cyan",
        )
    )

    icons = {"pending": "o", "running": "~", "done": "*", "failed": "x"}
    for tid, task in tasks.items():
        icon = icons.get(task["status"], "?")
        color = {"done": "green", "failed": "red"}.get(task["status"], "dim")
        console.print(
            f"  [{color}]{icon}[/{color}] {tid} [dim]Phase {task['phase']}[/dim] {task['description'][:55]}"
        )

    return (
        f"Brain for '{brain.get('project_name', '?')}': {len(tasks)} tasks, "
        f"{len(facts)} facts, phase {brain.get('current_phase', 0)}"
    )


async def _cmd_welcome() -> str:
    """Show the complete workflow guide."""
    guide = """
[bold cyan]CucumberSwarm — Workflow Guide[/bold cyan]

Du hast ein Projekt und willst es bauen? Der Swarm hilft dir in 3 Schritten:

[bold]1. [/bold][bold cyan]init[/bold cyan]   -> Projekt beim Swarm anmelden
[bold]2. [/bold][bold cyan]plan[/bold cyan]   -> SPEC.md analysieren, Phasen & Tasks erstellen
[bold]3. [/bold][bold cyan]run[/bold cyan]    -> Alle Tasks parallel von Agenten erledigen

[bold]Zusaetzliche Commands:[/bold]
  [dim]status[/dim]   -> Fortschritt anzeigen (laeuft gerade, was als naechstes)
  [dim]report[/dim]   -> Ergebnisse & erstellte Dateien
  [dim]brain[/dim]    -> Internes Gedaechtnis anzeigen
  [dim]reset[/dim]     -> Alles loeschen und von vorne anfangen

[bold]Typischer Ablauf:[/bold]

  # Projekt anmelden
  /herbert-swarm init /pfad/zum/projekt

  # Plan erstellen (einmalig nach init)
  /herbert-swarm plan /pfad/zum/projekt
  # -> LLM analysiert SPEC.md und erstellt Phasen + Tasks

  # Bauen!
  /herbert-swarm run /pfad/zum/projekt
  # -> Agenten arbeiten Tasks ab, parallel, bis alles fertig

  # Zwischendurch checken
  /herbert-swarm status /pfad/zum/projekt
  /herbert-swarm report /pfad/zum/projekt

[bold]Was passiert in jeder Phase?[/bold]

  [cyan]INFRA[/cyan]       -> Docker, Config, Environment-Setup
  [cyan]DATABASE[/cyan]    -> Models, Migrations, Schema
  [cyan]BACKEND[/cyan]     -> API Server, Routes, Business Logic
  [cyan]FRONTEND[/cyan]    -> Pages, Components, Styling
  [cyan]TESTING[/cyan]     -> Tests, CI/CD Pipeline

  Das System erkennt automatisch was dein Projekt braucht.

[bold]Was, wenn etwas schief geht?[/bold]

  # Fehlgeschlagene Tasks erneut versuchen
  /herbert-swarm run /pfad/zum/projekt retry_failed=true

  # Alles zuruecksetzen und neu starten
  /herbert-swarm reset /pfad/zum/projekt yes=true
  /herbert-swarm plan /pfad/zum/projekt
  /herbert-swarm run /pfad/zum/projekt

[dim]Tipp: Starte mit [bold]init[/bold] -> [bold]plan[/bold] -> [bold]run[/bold]. Die meisten Commands brauchst du nie.[/dim]
"""
    console.print(Panel(guide.strip(), border_style="cyan", padding=(1, 1)))
    return "Workflow guide shown above."


async def _cmd_reset(project: str | None, yes: bool = False) -> str:
    brain_file = _brain_file_for(project)
    brain = await _load_brain(brain_file)
    if brain is None:
        return f"No brain at {brain_file} — nothing to reset."

    project_name = brain.get("project_name", "?")
    if not yes:
        console.print(
            f"[yellow]Reset brain for '{project_name}'? (call with yes=true to confirm)[/yellow]"
        )
        return f"Reset cancelled. Pass yes=true to confirm reset of '{project_name}'."

    brain_file.unlink(missing_ok=True)
    console.print(f"[yellow]Brain for '{project_name}' reset.[/yellow]")
    return f"Brain for '{project_name}' reset."


# ---------------------------------------------------------------------------
# The Tool
# ---------------------------------------------------------------------------


class SwarmTool(BaseTool):
    """Herbert Swarm — native multi-agent project builder."""

    name = "swarm"
    description = (
        "CucumberSwarm: multi-agent parallel project builder. "
        "Analyzes a project SPEC.md, creates a phased execution plan, then spawns parallel "
        "sub-agents to implement each phase. "
        "Commands: init (set up swarm for a project), plan (create task plan from SPEC.md), "
        "run (execute all planned tasks with parallel agents), status (show progress), "
        "report (show results and files created), brain (show internal state), "
        "reset (clear brain). "
        "Always init -> plan -> run in sequence."
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "enum": ["welcome", "init", "plan", "run", "status", "report", "brain", "reset"],
                "description": "Subcommand to execute. Use 'welcome' first to see the complete workflow guide.",
            },
            "project": {
                "type": "string",
                "description": "Absolute path to the project directory",
            },
            "name": {
                "type": "string",
                "description": "Project name (for 'init' only, defaults to directory name)",
            },
            "spec": {
                "type": "string",
                "description": "Path to spec file for 'plan' (default: <project>/SPEC.md)",
            },
            "parallel": {
                "type": "integer",
                "description": "Max parallel agents for 'run' (default: 3)",
            },
            "timeout": {
                "type": "integer",
                "description": "Per-agent timeout in seconds for 'run' (default: 600)",
            },
            "dry_run": {
                "type": "boolean",
                "description": "If true, 'run' simulates without calling any agents",
            },
            "retry_failed": {
                "type": "boolean",
                "description": "If true, 'run' only retries failed tasks",
            },
            "yes": {
                "type": "boolean",
                "description": "Skip confirmation prompt for 'reset'",
            },
        },
        "required": ["command"],
    }

    async def execute(  # noqa: PLR0913
        self,
        command: str,
        project: str | None = None,
        name: str | None = None,
        spec: str | None = None,
        parallel: int = 3,
        timeout: int = 600,
        dry_run: bool = False,
        retry_failed: bool = False,
        yes: bool = False,
    ) -> ToolResult:
        try:
            if command == "welcome":
                out = await _cmd_welcome()
            elif command == "init":
                if not project:
                    return ToolResult(
                        success=False, output="", error="'project' path is required for init"
                    )
                out = await _cmd_init(project, name)
            elif command == "plan":
                if not project:
                    return ToolResult(
                        success=False, output="", error="'project' path is required for plan"
                    )
                out = await _cmd_plan(project, spec)
            elif command == "run":
                if not project:
                    return ToolResult(
                        success=False, output="", error="'project' path is required for run"
                    )
                out = await _cmd_run(
                    project,
                    parallel=parallel,
                    timeout=timeout,
                    dry_run=dry_run,
                    retry_failed=retry_failed,
                )
            elif command == "status":
                out = await _cmd_status(project)
            elif command == "report":
                out = await _cmd_report(project)
            elif command == "brain":
                out = await _cmd_brain(project)
            elif command == "reset":
                out = await _cmd_reset(project, yes=yes)
            else:
                return ToolResult(success=False, output="", error=f"Unknown command: {command}")

            return ToolResult(success=True, output=out)
        except Exception as e:
            logger.exception("Swarm tool execution failed")
            return ToolResult(success=False, output="", error=f"Swarm error: {e}")


ToolRegistry.register(SwarmTool())
