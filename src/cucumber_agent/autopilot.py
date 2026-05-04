"""Project-local Agent Autopilot state, planning, and execution helpers."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shlex
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from cucumber_agent.tools import ToolRegistry

AUTOPILOT_VERSION = 1


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def default_autopilot_dir(config_dir: Path | None = None) -> Path:
    """Return the global local Autopilot state directory."""
    return (config_dir or (Path.home() / ".cucumber")) / "autopilot"


def workspace_key(workspace: Path | str) -> str:
    """Stable key for a workspace path, used as state filename."""
    resolved = str(Path(workspace).expanduser().resolve())
    return hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:16]


@dataclass
class AutopilotTask:
    id: str
    title: str
    detail: str
    agent_role: str
    priority: int
    status: str = "pending"
    execution: str = "agent"
    result: str = ""
    error: str = ""
    started_at: str = ""
    completed_at: str = ""


@dataclass
class AutopilotState:
    version: int
    workspace: str
    goal: str
    tasks: list[AutopilotTask] = field(default_factory=list)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    last_run_at: str = ""
    last_report: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AutopilotState:
        tasks = [AutopilotTask(**task) for task in data.get("tasks", [])]
        return cls(
            version=int(data.get("version", AUTOPILOT_VERSION)),
            workspace=str(data.get("workspace", "")),
            goal=str(data.get("goal", "")),
            tasks=tasks,
            created_at=str(data.get("created_at", _now())),
            updated_at=str(data.get("updated_at", _now())),
            last_run_at=str(data.get("last_run_at", "")),
            last_report=str(data.get("last_report", "")),
        )


class AutopilotStore:
    """JSON store under ~/.cucumber/autopilot, keyed by workspace."""

    def __init__(self, workspace: Path | str, state_dir: Path | str | None = None) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        self.state_dir = Path(state_dir) if state_dir else default_autopilot_dir()
        self.path = self.state_dir / f"{workspace_key(self.workspace)}.json"

    def load(self) -> AutopilotState | None:
        if not self.path.exists():
            return None
        try:
            return AutopilotState.from_dict(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return None

    def save(self, state: AutopilotState) -> None:
        state.updated_at = _now()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(asdict(state), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def reset(self) -> bool:
        if self.path.exists():
            self.path.unlink()
            return True
        return False


def _has_any(workspace: Path, filenames: set[str]) -> bool:
    return any((workspace / name).exists() for name in filenames)


def create_plan(goal: str, workspace: Path | str) -> AutopilotState:
    """Create a broad, deterministic V1 plan for a project goal."""
    workspace_path = Path(workspace).expanduser().resolve()
    cleaned_goal = goal.strip() or "Projekt verbessern und stabilisieren"
    tasks: list[AutopilotTask] = []

    def add(title: str, detail: str, role: str, priority: int) -> None:
        tasks.append(
            AutopilotTask(
                id=f"task-{len(tasks) + 1:03d}",
                title=title,
                detail=detail,
                agent_role=role,
                priority=priority,
            )
        )

    add(
        "Projektzustand analysieren",
        "Workspace, bestehende Doku, Tests, offene Risiken und passende Umsetzungspfade erfassen.",
        "planner",
        1,
    )
    add(
        "Ziel in umsetzbare Arbeit schneiden",
        f"Das Ziel '{cleaned_goal}' in kleine, testbare Schritte mit klaren Ergebnissen zerlegen.",
        "planner",
        2,
    )

    if _has_any(workspace_path, {"pyproject.toml", "setup.py", "requirements.txt"}):
        add(
            "Python-Code und Schnittstellen verbessern",
            "Betroffene Module implementieren oder refactoren und bestehende Patterns beibehalten.",
            "coder",
            3,
        )
        add(
            "Python-Tests und Typchecks absichern",
            "Gezielte pytest-, ruff- und pyright-Abdeckung fuer die Aenderung ergaenzen.",
            "tester",
            4,
        )

    if _has_any(workspace_path, {"package.json", "vite.config.ts", "next.config.js"}):
        add(
            "Frontend-Erlebnis pruefen und verbessern",
            "UI-Flows, Responsiveness, Textueberlauf und erwartbare Interaktionen absichern.",
            "frontend",
            4,
        )

    add(
        "Integration ausfuehren",
        "Geplante Tasks mit passenden Agenten ausfuehren, Ergebnisse speichern und Fehler sichtbar machen.",
        "coder",
        5,
    )
    add(
        "Review und Abschlussbericht erstellen",
        "Aenderungen, Tests, Rest-Risiken und naechste Schritte kompakt zusammenfassen.",
        "reviewer",
        6,
    )

    return AutopilotState(
        version=AUTOPILOT_VERSION,
        workspace=str(workspace_path),
        goal=cleaned_goal,
        tasks=tasks,
    )


def status_text(state: AutopilotState | None) -> str:
    if state is None:
        return "Autopilot: kein Plan fuer diesen Workspace. Nutze /autopilot plan <ziel>."

    counts = {
        "pending": 0,
        "running": 0,
        "done": 0,
        "failed": 0,
    }
    for task in state.tasks:
        counts[task.status] = counts.get(task.status, 0) + 1
    next_task = next((task for task in state.tasks if task.status in {"pending", "failed"}), None)
    suffix = f"\nNaechster Task: {next_task.id} - {next_task.title}" if next_task else ""
    return (
        f"Autopilot: {state.goal}\n"
        f"Workspace: {state.workspace}\n"
        f"Tasks: {counts.get('done', 0)} done, {counts.get('pending', 0)} pending, "
        f"{counts.get('failed', 0)} failed{suffix}"
    )


def report_text(state: AutopilotState | None) -> str:
    if state is None:
        return "Autopilot: kein Report vorhanden. Nutze /autopilot plan <ziel>."

    lines = [
        f"Autopilot Report: {state.goal}",
        f"Workspace: {state.workspace}",
        f"Stand: {state.updated_at}",
        "",
    ]
    for task in state.tasks:
        marker = {
            "done": "[done]",
            "failed": "[failed]",
            "running": "[running]",
        }.get(task.status, "[pending]")
        detail = task.error or task.result or task.detail
        lines.append(f"- {marker} {task.id} {task.title}: {detail}")
    return "\n".join(lines)


async def run_plan(
    state: AutopilotState,
    *,
    parallel: int = 3,
    timeout: int = 300,
    dry_run: bool = False,
) -> AutopilotState:
    """Execute pending Autopilot tasks via the existing agent tool."""
    if parallel < 1:
        raise ValueError("--parallel muss mindestens 1 sein")
    if parallel > 12:
        raise ValueError("--parallel darf maximal 12 sein")
    if timeout < 1:
        raise ValueError("--timeout muss mindestens 1 Sekunde sein")

    pending = [task for task in state.tasks if task.status in {"pending", "failed"}]
    state.last_run_at = _now()

    if dry_run:
        for task in pending:
            task.status = "done"
            task.result = "DRY RUN: Task wuerde ausgefuehrt."
            task.error = ""
            task.started_at = state.last_run_at
            task.completed_at = _now()
        state.last_report = report_text(state)
        return state

    agent_tool = ToolRegistry.get("agent")
    if agent_tool is None:
        raise RuntimeError("Das agent Tool ist nicht registriert.")

    semaphore = asyncio.Semaphore(parallel)

    async def execute_task(task: AutopilotTask) -> None:
        async with semaphore:
            task.status = "running"
            task.started_at = _now()
            prompt = (
                f"Agent Autopilot task for workspace: {state.workspace}\n"
                f"Overall goal: {state.goal}\n"
                f"Task: {task.title}\n\n"
                f"Details: {task.detail}\n\n"
                "Work only inside the workspace. Preserve unrelated user changes. "
                "Use existing project patterns and finish with a concise summary."
            )
            try:
                result = await asyncio.wait_for(agent_tool.execute(task=prompt), timeout=timeout)
            except TimeoutError:
                task.status = "failed"
                task.error = f"Timed out after {timeout}s"
            except Exception as exc:
                task.status = "failed"
                task.error = str(exc)[:500]
            else:
                if result.success:
                    task.status = "done"
                    task.result = (result.output or "").strip()[:800]
                    task.error = ""
                else:
                    task.status = "failed"
                    task.error = (result.error or result.output or "unknown error")[:500]
            task.completed_at = _now()

    await asyncio.gather(*(execute_task(task) for task in pending))
    state.last_report = report_text(state)
    return state


def parse_autopilot_args(args: str) -> SimpleNamespace:
    tokens = shlex.split(args)
    action = "status"
    parallel = 3
    timeout = 300
    dry_run = False
    yes = False
    goal_parts: list[str] = []
    actions = {"plan", "run", "status", "report", "reset"}

    i = 0
    while i < len(tokens):
        token = tokens[i]
        normalized = token.strip().strip(".,;:!?").lower()
        if normalized in actions and action == "status":
            action = normalized
        elif token == "--dry-run":
            dry_run = True
        elif token == "--yes":
            yes = True
        elif token in {"--parallel", "-p"} and i + 1 < len(tokens):
            i += 1
            parallel = int(tokens[i])
        elif token in {"--timeout", "-t"} and i + 1 < len(tokens):
            i += 1
            timeout = int(tokens[i])
        elif token.startswith("-"):
            raise ValueError(f"Unbekannte Autopilot-Option: {token}")
        else:
            goal_parts.append(token)
        i += 1

    if parallel < 1:
        raise ValueError("--parallel muss mindestens 1 sein")
    if parallel > 12:
        raise ValueError("--parallel darf maximal 12 sein")
    if timeout < 1:
        raise ValueError("--timeout muss mindestens 1 Sekunde sein")

    return SimpleNamespace(
        action=action,
        goal=" ".join(goal_parts).strip(),
        parallel=parallel,
        timeout=timeout,
        dry_run=dry_run,
        yes=yes,
    )
