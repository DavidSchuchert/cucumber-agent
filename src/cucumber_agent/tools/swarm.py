"""Herbert Swarm — native multi-agent project builder, integrated into cucumber-agent."""

from __future__ import annotations

import asyncio
import json
import re
import threading
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from cucumber_agent.session import Message, Role
from cucumber_agent.tools.base import BaseTool, ToolResult
from cucumber_agent.tools.registry import ToolRegistry

console = Console()

# ---------------------------------------------------------------------------
# Brain storage helpers
# ---------------------------------------------------------------------------

_brain_file_lock = threading.Lock()
_SWARM_HOME = Path.home() / ".local" / "share" / "cucumber-swarm"


def _brain_file_for(project_path: str | Path | None) -> Path:
    if project_path:
        return Path(project_path).resolve() / ".swarm_brain.json"
    return _SWARM_HOME / "brain.json"


def _load_brain(brain_file: Path) -> dict | None:
    if not brain_file.exists():
        return None
    with _brain_file_lock:
        try:
            return json.loads(brain_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None


def _save_brain(brain: dict, brain_file: Path) -> None:
    brain_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = brain_file.with_suffix(".json.tmp")
    with _brain_file_lock:
        tmp.write_text(json.dumps(brain, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(brain_file)


# ---------------------------------------------------------------------------
# Project analysis + planning (ported from Herbert Swarm 2.0)
# ---------------------------------------------------------------------------

def _scan_project_files(project_path: Path) -> set[str]:
    found: set[str] = set()
    try:
        for entry in project_path.rglob("*"):
            if entry.is_file():
                found.add(entry.name.lower())
    except Exception:
        pass
    return found


def _add_phase(phase_names: list[str], phase_map: dict[str, int], name: str) -> int:
    phase = len(phase_names) + 1
    phase_names.append(name)
    phase_map[name] = phase
    return phase


def _has_keyword(text: str, keywords: list[str]) -> bool:
    for keyword in keywords:
        pattern = rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])"
        if re.search(pattern, text):
            return True
    return False


def _analyze_and_plan(spec_content: str, project_path: Path) -> tuple[dict, list[str]]:
    lower = spec_content.lower()

    backend_kw = [
        "fastapi", "flask", "django", "starlette", "express", "aiohttp", "tornado",
        "backend", "python", "api", "rest", "graphql", "grpc", "server", "endpoint",
        "routes", "uvicorn", "gunicorn",
    ]
    frontend_kw = [
        "react", "next.js", "nextjs", "nuxt", "sveltekit", "svelte", "vue", "vite",
        "angular", "astro", "remix", "frontend", "typescript", "tailwind", "html",
        "css", "ui", "web app",
    ]
    database_kw = [
        "postgresql", "postgres", "mysql", "mariadb", "mongodb", "mongo", "redis",
        "sqlite", "cassandra", "elasticsearch", "database", "db", "sqlalchemy",
        "prisma", "alembic", "migration",
    ]
    docker_kw = ["docker", "container", "compose", "kubernetes", "k8s", "helm"]
    ci_kw = [
        "github actions", "github-actions", "ci", "pytest-cov", "coverage", "test",
        "pytest", "unittest", "jest", "vitest", "cypress",
    ]

    has_backend  = _has_keyword(lower, backend_kw)
    has_frontend = _has_keyword(lower, frontend_kw)
    has_database = _has_keyword(lower, database_kw)
    has_docker   = _has_keyword(lower, docker_kw)
    has_ci       = _has_keyword(lower, ci_kw)

    if not spec_content.strip() or len(spec_content.strip()) < 80:
        files = _scan_project_files(project_path)
        if not has_backend:
            has_backend = bool(
                files
                & {"requirements.txt", "pyproject.toml", "setup.py", "main.py", "app.py",
                   "server.py", "manage.py"}
            )
        if not has_frontend:
            has_frontend = bool(
                files
                & {"package.json", "vite.config.ts", "vite.config.js", "next.config.js",
                   "nuxt.config.ts", "svelte.config.js", "tailwind.config.js",
                   "tailwind.config.ts"}
            )
        if not has_docker:
            has_docker = bool(files & {"dockerfile", "docker-compose.yml", "docker-compose.yaml"})
        if not has_ci:
            has_ci = bool(files & {"pytest.ini", "conftest.py"})

    tasks: dict = {}
    task_id = 1

    def make_task(
        desc: str,
        role: str,
        files: list[str],
        deps: Sequence[str | None],
        phase: int,
        priority: int,
    ) -> dict:
        nonlocal task_id
        tid = f"task-{task_id:03d}"
        task_id += 1
        return {
            "id": tid,
            "description": desc,
            "agent_role": role,
            "files": files,
            "dependencies": [d for d in deps if d],
            "status": "pending",
            "priority": priority,
            "phase": phase,
            "created_by": "planner",
        }

    phase_names: list[str] = ["INFRA"]
    phase_map: dict[str, int] = {"INFRA": 1}

    if has_database:
        _add_phase(phase_names, phase_map, "DATABASE")
    if has_backend:
        _add_phase(phase_names, phase_map, "BACKEND_CORE")
        _add_phase(phase_names, phase_map, "BACKEND_API")
    if has_frontend:
        _add_phase(phase_names, phase_map, "FRONTEND")
    if has_ci:
        _add_phase(phase_names, phase_map, "TESTING")

    infra_files: list[str] = []
    if has_docker:
        infra_files += [
            "docker/docker-compose.yml",
            "docker/docker-compose.dev.yml",
            "docker/backend/Dockerfile",
            "docker/frontend/Dockerfile",
            "docker/.env.example",
        ]
    if has_backend:
        infra_files += ["backend/requirements.txt", "backend/config.py"]
    if has_frontend:
        infra_files += [
            "frontend/package.json",
            "frontend/vite.config.ts",
            "frontend/tailwind.config.js",
        ]

    infra_id: str | None = None
    if infra_files:
        t = make_task(
            "Create infrastructure and configuration files",
            "coder",
            infra_files,
            [],
            phase_map["INFRA"],
            1,
        )
        infra_id = t["id"]
        tasks[infra_id] = t

    db_model_id: str | None = None
    if has_database and "DATABASE" in phase_map:
        t = make_task(
            "Create database models and migration scripts",
            "coder",
            ["backend/core/database.py", "backend/models/__init__.py", "alembic/env.py"],
            [infra_id],
            phase_map["DATABASE"],
            2,
        )
        db_model_id = t["id"]
        tasks[db_model_id] = t

    core_task_ids: list[str] = []
    if has_backend and "BACKEND_CORE" in phase_map:
        core_deps = [infra_id, db_model_id]
        if not has_database:
            t = make_task(
                "Create database connection layer",
                "coder",
                ["backend/core/database.py", "backend/models/base.py"],
                core_deps,
                phase_map["BACKEND_CORE"],
                2,
            )
        else:
            t = make_task(
                "Create core services: business logic and helpers",
                "coder",
                ["backend/core/service.py", "backend/core/utils.py"],
                core_deps,
                phase_map["BACKEND_CORE"],
                2,
            )
        core_task_ids.append(t["id"])
        tasks[t["id"]] = t

    api_id: str | None = None
    if has_backend and "BACKEND_API" in phase_map:
        t = make_task(
            "Create API endpoints",
            "coder",
            ["backend/api/routes.py", "backend/main.py"],
            core_task_ids,
            phase_map["BACKEND_API"],
            3,
        )
        api_id = t["id"]
        tasks[api_id] = t

    fe_task_ids: list[str] = []
    if has_frontend and "FRONTEND" in phase_map:
        fe_deps = [infra_id, api_id]
        t = make_task(
            "Create main pages",
            "coder",
            ["frontend/src/pages/index.tsx", "frontend/src/App.tsx"],
            fe_deps,
            phase_map["FRONTEND"],
            4,
        )
        t2 = make_task(
            "Create UI components",
            "coder",
            ["frontend/src/components/Layout.tsx", "frontend/src/components/Card.tsx"],
            fe_deps,
            phase_map["FRONTEND"],
            4,
        )
        fe_task_ids += [t["id"], t2["id"]]
        tasks[t["id"]] = t
        tasks[t2["id"]] = t2

    if has_ci and "TESTING" in phase_map and (api_id or fe_task_ids or core_task_ids):
        t = make_task(
            "Create tests for API and core services",
            "reviewer",
            ["tests/test_api.py", "tests/conftest.py"],
            [api_id] + fe_task_ids,
            phase_map["TESTING"],
            5,
        )
        tasks[t["id"]] = t

    if not tasks and spec_content.strip():
        phase_names = ["IMPLEMENTATION"]
        t = make_task(
            "Implement the project requirements described in SPEC.md",
            "coder",
            ["README.md"],
            [],
            1,
            1,
        )
        tasks[t["id"]] = t

    return tasks, phase_names


# ---------------------------------------------------------------------------
# Agent prompt builder
# ---------------------------------------------------------------------------

def _build_agent_prompt(task: dict, brain: dict, brain_file: Path) -> str:
    project_path = str(Path(brain.get("project_path", ".")).resolve())
    spec_summary = brain.get("spec_summary", "")
    tid          = task["id"]
    files        = "\n".join(f"  - {f}" for f in task["files"])
    spec_ctx     = f"\nPROJECT SPEC (summary):\n{spec_summary[:800]}\n" if spec_summary else ""

    brain_update = (
        f"\nAFTER completing ALL files, update the brain file at: {brain_file}\n"
        f"  1. Read the JSON: shell cat {brain_file}\n"
        f"  2. Add to brain[\"facts\"][\"task_{tid}_result\"]:\n"
        f"     {{\"files_created\": [<absolute paths>], \"summary\": \"<one sentence>\"}}\n"
        f"  3. Write updated JSON back to {brain_file}\n"
    )

    return (
        f"You are a {task['agent_role']} agent in the CucumberSwarm.\n"
        f"Working directory (absolute): {project_path}\n"
        f"All files you create/modify must be INSIDE this directory.\n"
        f"{spec_ctx}\n"
        f"TASK: {task['description']}\n\n"
        f"Files to create/modify:\n{files}\n\n"
        f"Implement the task completely with production-ready code. No TODOs or placeholders.\n"
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


async def _run_task_async(tid: str, task: dict, brain: dict, brain_file: Path) -> dict:
    from cucumber_agent.agent import Agent
    from cucumber_agent.config import Config
    from cucumber_agent.session import Session
    from cucumber_agent.tools import agent as agent_tool_module

    config = Config.load()
    agent  = Agent.from_config(config)
    session = Session(id=f"swarm-{tid}", model=config.agent.model)
    project_path = Path(brain.get("project_path", ".")).resolve()

    # Sub-agents in swarm auto-approve tool calls — user initiated the swarm intentionally
    old_approve = agent_tool_module._subagent_auto_approve
    agent_tool_module._subagent_auto_approve = True

    prompt = _build_agent_prompt(task, brain, brain_file)

    try:
        current_input = prompt
        max_steps = 12
        for step in range(max_steps):
            response = await agent.run_with_tools(session, current_input)
            if not response.tool_calls:
                return {"success": True, "output": (response.content or "")[:600]}
            for tc in response.tool_calls:
                tool_args, blocked = _normalize_swarm_tool_args(
                    tc.name,
                    tc.arguments,
                    project_path,
                )
                if blocked is not None:
                    return blocked
                result = await ToolRegistry.execute(tc.name, **(tool_args or {}))
                output_text = (
                    result.output if result.success else "ERROR: " + (result.error or result.output)
                )
                if len(output_text) > 3000:
                    output_text = output_text[:1500] + "\n... [TRUNCATED] ...\n" + output_text[-1500:]
                if not result.success and not output_text.strip():
                    output_text = "ERROR: Tool failed without stderr/output"
                session.messages.append(
                    Message(
                        role=Role.TOOL,
                        content=output_text,
                        name=tc.name,
                        tool_call_id=tc.id,
                    )
                )
            current_input = (
                "Continue. Execute remaining steps, then provide a final summary "
                "of what was created."
            )
        return {"success": False, "output": "Step limit reached before task completion"}
    except Exception as e:
        return _format_failure(str(e), error_type=type(e).__name__)
    finally:
        agent_tool_module._subagent_auto_approve = old_approve
        provider = getattr(agent, "_provider", None)
        close = getattr(provider, "close", None)
        if close is not None:
            try:
                await close()
            except Exception:
                pass


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
# Command implementations
# ---------------------------------------------------------------------------

def _cmd_init(project: str, name: str | None = None) -> str:
    project_path = Path(project).resolve()
    project_name = name or project_path.name
    brain_file   = _brain_file_for(project_path)

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
    _save_brain(brain, brain_file)

    console.print(Panel(
        f"[bold green]Swarm initialized[/bold green]\n"
        f"[bold]Project:[/bold] {project_name}\n"
        f"[bold]Path:[/bold]    {project_path}\n"
        f"[bold]Brain:[/bold]   {brain_file}",
        title="[bold cyan]🐝 CucumberSwarm[/bold cyan]",
        border_style="cyan",
    ))
    return f"Swarm initialized for '{project_name}' at {project_path}. Brain: {brain_file}"


def _cmd_plan(project: str, spec: str | None = None) -> str:
    project_path = Path(project).resolve()
    brain_file   = _brain_file_for(project_path)
    brain        = _load_brain(brain_file)
    if brain is None:
        return f"ERROR: No swarm brain at {brain_file}. Run 'init' first."

    spec_path = Path(spec).resolve() if spec else project_path / "SPEC.md"
    if spec_path.exists():
        spec_content = spec_path.read_text(encoding="utf-8")
        brain["spec_summary"] = spec_content[:2000]
    else:
        spec_content = ""
        console.print(f"[yellow]No spec file at {spec_path} — scanning project files[/yellow]")

    tasks, phases = _analyze_and_plan(spec_content, project_path)
    brain["tasks"]  = tasks
    brain["phases"] = phases
    _save_brain(brain, brain_file)

    lines = [f"[bold]Plan created:[/bold] {len(tasks)} tasks across {len(phases)} phases\n"]
    for i, phase_name in enumerate(phases, 1):
        phase_tasks = [t for t in tasks.values() if t["phase"] == i]
        lines.append(f"  Phase {i}: [cyan]{phase_name}[/cyan] ({len(phase_tasks)} tasks)")

    console.print(Panel("\n".join(lines), title="[bold cyan]🐝 CucumberSwarm — Plan[/bold cyan]", border_style="cyan"))
    return f"Plan: {len(tasks)} tasks across {len(phases)} phases ({', '.join(phases)})"


async def _cmd_run(
    project: str,
    parallel: int = 3,
    timeout: int = 300,
    dry_run: bool = False,
    retry_failed: bool = False,
) -> str:
    if parallel < 1:
        return "ERROR: parallel must be at least 1."
    if timeout < 1:
        return "ERROR: timeout must be at least 1 second."

    project_path = Path(project).resolve()
    brain_file   = _brain_file_for(project_path)
    brain        = _load_brain(brain_file)
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
        _save_brain(brain, brain_file)

    run_start = datetime.now()
    console.print(Panel(
        f"[bold]Project:[/bold]  {brain['project_name']}\n"
        f"[bold]Tasks:[/bold]    {len(brain['tasks'])}\n"
        f"[bold]Phases:[/bold]   {', '.join(brain.get('phases', []))}\n"
        f"[bold]Parallel:[/bold] {parallel}  [bold]Timeout:[/bold] {timeout}s/agent"
        + ("\n[yellow]DRY RUN — no agents called[/yellow]" if dry_run else ""),
        title="[bold cyan]🐝 CucumberSwarm — Execution[/bold cyan]",
        border_style="cyan",
    ))

    semaphore = asyncio.Semaphore(parallel)

    for phase_num, phase_name in enumerate(brain.get("phases", []), 1):
        phase_tasks = [
            (tid, t) for tid, t in brain["tasks"].items()
            if t["phase"] == phase_num and t["status"] == "pending"
        ]
        if not phase_tasks:
            continue

        console.print(f"\n[bold cyan]── Phase {phase_num}: {phase_name} ──[/bold cyan] "
                      f"({len(phase_tasks)} tasks, max {parallel} parallel)")

        for tid, task in phase_tasks:
            task["status"] = "running"
            task["started_at"] = datetime.now().isoformat()
        _save_brain(brain, brain_file)

        if dry_run:
            for tid, task in phase_tasks:
                task["status"] = "done"
                task["completed_at"] = datetime.now().isoformat()
                console.print(f"  [yellow][DRY][/yellow] [cyan]{tid}[/cyan]: {task['description'][:55]}")
        else:
            async def run_one(tid: str, task: dict) -> tuple[str, dict]:
                async with semaphore:
                    try:
                        result = await asyncio.wait_for(
                            _run_task_async(tid, task, brain, brain_file),
                            timeout=timeout,
                        )
                    except TimeoutError:
                        result = _format_failure(
                            f"Timed out after {timeout}s",
                            error_type="TimeoutError",
                        )
                    except Exception as exc:
                        result = _format_failure(str(exc), error_type=type(exc).__name__)

                    ok = result.get("success", False)
                    status_icon = "[green]✓[/green]" if ok else "[red]✗[/red]"
                    console.print(
                        f"  {status_icon} [cyan]{tid}[/cyan]: {task['description'][:55]}"
                    )
                    if not ok:
                        console.print(
                            f"    [red]Error:[/red] {_task_error_summary(result)[:240]}"
                        )
                    return tid, result

            result_pairs = await asyncio.gather(
                *(run_one(tid, task) for tid, task in phase_tasks)
            )
            results = dict(result_pairs)

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
                    task["error"]  = _task_error_summary(r)[:500]
                    task["error_details"] = {
                        key: value
                        for key, value in r.items()
                        if key not in {"success"}
                    }
                task["completed_at"] = datetime.now().isoformat()

        _save_brain(brain, brain_file)
        brain["current_phase"] = phase_num
        _save_brain(brain, brain_file)

    done    = sum(1 for t in brain["tasks"].values() if t["status"] == "done")
    failed  = sum(1 for t in brain["tasks"].values() if t["status"] == "failed")
    total   = len(brain["tasks"])
    elapsed = int((datetime.now() - run_start).total_seconds())

    summary_table = Table.grid(padding=(0, 2))
    summary_table.add_row("[bold]Done:[/bold]",    f"[green]{done}/{total}[/green]")
    summary_table.add_row("[bold]Failed:[/bold]",  f"[red]{failed}[/red]" if failed else "0")
    summary_table.add_row("[bold]Elapsed:[/bold]", f"{elapsed}s")
    console.print(Panel(summary_table, title="[bold cyan]🐝 CucumberSwarm — Complete[/bold cyan]", border_style="cyan"))

    suffix = f" ({failed} failed — run 'swarm run --retry-failed' to retry)" if failed else ""
    return f"Swarm complete: {done}/{total} tasks done{suffix}"


def _cmd_status(project: str | None) -> str:
    brain_file = _brain_file_for(project)
    brain      = _load_brain(brain_file)
    if brain is None:
        return f"No brain found at {brain_file}. Run 'init' first."

    tasks = brain.get("tasks", {})
    if not tasks:
        return "No tasks — run 'plan' first."

    by_status: dict[str, int] = {}
    for t in tasks.values():
        by_status[t["status"]] = by_status.get(t["status"], 0) + 1

    lines = [f"[bold]Project:[/bold] {brain.get('project_name','?')}  "
             f"[bold]Tasks:[/bold] {len(tasks)}\n"]
    icons = {"pending": "○", "running": "◐", "done": "●", "failed": "✗"}
    for status, count in sorted(by_status.items()):
        icon = icons.get(status, "?")
        color = {"done": "green", "failed": "red", "running": "yellow"}.get(status, "dim")
        lines.append(f"  [{color}]{icon} {status}:[/{color}] {count}")

    for phase_num, phase_name in enumerate(brain.get("phases", []), 1):
        phase_tasks = [t for t in tasks.values() if t["phase"] == phase_num]
        done   = sum(1 for t in phase_tasks if t["status"] == "done")
        failed = sum(1 for t in phase_tasks if t["status"] == "failed")
        bar = "●" * done + "✗" * failed + "○" * (len(phase_tasks) - done - failed)
        lines.append(f"\n  Phase {phase_num} [cyan]{phase_name}[/cyan]: [{bar}] {done}/{len(phase_tasks)}")

    console.print(Panel("\n".join(lines), title="[bold cyan]🐝 CucumberSwarm — Status[/bold cyan]", border_style="cyan"))

    parts = [f"{s}: {c}" for s, c in sorted(by_status.items())]
    return f"Status for '{brain.get('project_name','?')}': " + ", ".join(parts)


def _cmd_report(project: str | None) -> str:
    brain_file = _brain_file_for(project)
    brain      = _load_brain(brain_file)
    if brain is None:
        return f"No brain at {brain_file}. Run 'init' first."

    tasks = brain.get("tasks", {})
    facts = brain.get("facts", {})

    total   = len(tasks)
    done    = sum(1 for t in tasks.values() if t["status"] == "done")
    failed  = sum(1 for t in tasks.values() if t["status"] == "failed")
    pending = sum(1 for t in tasks.values() if t["status"] == "pending")
    pct     = f"{done/total*100:.0f}%" if total else "0%"

    all_files: list[str] = []
    for tid, task in tasks.items():
        fact = facts.get(f"task_{tid}_result", {})
        if isinstance(fact, dict):
            for f in fact.get("files_created", []):
                if f not in all_files:
                    all_files.append(f)

    report_table = Table.grid(padding=(0, 2))
    report_table.add_row("[bold]Project:[/bold]",  brain.get("project_name", "?"))
    report_table.add_row("[bold]Done:[/bold]",     f"[green]{done}/{total}[/green] ({pct})")
    if failed:
        report_table.add_row("[bold]Failed:[/bold]", f"[red]{failed}[/red]")
    if pending:
        report_table.add_row("[bold]Pending:[/bold]", str(pending))
    if all_files:
        report_table.add_row("[bold]Files:[/bold]", str(len(all_files)))

    console.print(Panel(report_table, title="[bold cyan]🐝 CucumberSwarm — Report[/bold cyan]", border_style="cyan"))

    if all_files:
        for f in all_files[:20]:
            exists = Path(f).exists()
            console.print(f"  {'[green]✓[/green]' if exists else '[yellow]?[/yellow]'} {f}")

    if failed:
        for tid, task in tasks.items():
            if task["status"] == "failed":
                error = task.get("error", "") or "Tool failed without stderr/output"
                console.print(f"  [red]✗[/red] {tid}: {error[:220]}")
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


def _cmd_brain(project: str | None) -> str:
    brain_file = _brain_file_for(project)
    brain      = _load_brain(brain_file)
    if brain is None:
        return f"No brain at {brain_file}. Run 'init' first."

    tasks = brain.get("tasks", {})
    facts = brain.get("facts", {})

    lines = [
        f"[bold]Project:[/bold]  {brain.get('project_name','?')}",
        f"[bold]Path:[/bold]     {brain.get('project_path','?')}",
        f"[bold]Created:[/bold]  {brain.get('created_at','?')}",
        f"[bold]Phase:[/bold]    {brain.get('current_phase',0)} / {len(brain.get('phases',[]))}",
        f"[bold]Tasks:[/bold]    {len(tasks)}  [bold]Facts:[/bold] {len(facts)}",
    ]
    console.print(Panel("\n".join(lines), title="[bold cyan]🐝 CucumberSwarm — Brain[/bold cyan]", border_style="cyan"))

    icons = {"pending": "○", "running": "◐", "done": "●", "failed": "✗"}
    for tid, task in tasks.items():
        icon  = icons.get(task["status"], "?")
        color = {"done": "green", "failed": "red"}.get(task["status"], "dim")
        console.print(f"  [{color}]{icon}[/{color}] {tid} [dim]Phase {task['phase']}[/dim] {task['description'][:55]}")

    return (f"Brain for '{brain.get('project_name','?')}': {len(tasks)} tasks, "
            f"{len(facts)} facts, phase {brain.get('current_phase',0)}")


def _cmd_reset(project: str | None, yes: bool = False) -> str:
    brain_file = _brain_file_for(project)
    brain      = _load_brain(brain_file)
    if brain is None:
        return f"No brain at {brain_file} — nothing to reset."

    project_name = brain.get("project_name", "?")
    if not yes:
        console.print(f"[yellow]Reset brain for '{project_name}'? (call with yes=true to confirm)[/yellow]")
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
        "Always init → plan → run in sequence."
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "enum": ["init", "plan", "run", "status", "report", "brain", "reset"],
                "description": "Subcommand to execute",
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
                "description": "Per-agent timeout in seconds for 'run' (default: 300)",
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
        timeout: int = 300,
        dry_run: bool = False,
        retry_failed: bool = False,
        yes: bool = False,
    ) -> ToolResult:
        try:
            if command == "init":
                if not project:
                    return ToolResult(success=False, output="", error="'project' path is required for init")
                out = _cmd_init(project, name)
            elif command == "plan":
                if not project:
                    return ToolResult(success=False, output="", error="'project' path is required for plan")
                out = _cmd_plan(project, spec)
            elif command == "run":
                if not project:
                    return ToolResult(success=False, output="", error="'project' path is required for run")
                out = await _cmd_run(project, parallel=parallel, timeout=timeout,
                                     dry_run=dry_run, retry_failed=retry_failed)
            elif command == "status":
                out = _cmd_status(project)
            elif command == "report":
                out = _cmd_report(project)
            elif command == "brain":
                out = _cmd_brain(project)
            elif command == "reset":
                out = _cmd_reset(project, yes=yes)
            else:
                return ToolResult(success=False, output="", error=f"Unknown command: {command}")

            return ToolResult(success=True, output=out)
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Swarm error: {e}")


ToolRegistry.register(SwarmTool())
