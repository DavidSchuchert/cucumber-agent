"""Skill runner — executes a skill by injecting its prompt into the agent."""

from __future__ import annotations

import asyncio
import re
import shlex
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

from cucumber_agent.session import Message, Role
from cucumber_agent.tools import ToolRegistry

if TYPE_CHECKING:
    from cucumber_agent.agent import Agent
    from cucumber_agent.session import Session
    from cucumber_agent.skills.loader import Skill, SkillLoader


class SkillRunner:
    """Runs a Skill by expanding its prompt template and sending it to the agent."""

    @staticmethod
    def _default_workspace(agent: Agent) -> Path:
        config = getattr(agent, "_config", None)
        workspace = getattr(config, "workspace", None)
        return Path(workspace or Path.cwd()).expanduser().resolve()

    @staticmethod
    def _extract_parallel_from_text(args: str) -> int | None:
        lower = args.lower()
        patterns = [
            r"(?:parallel\w*|parralel\w*|parralele|agenten|agents)\D{0,20}(\d{1,2})",
            r"(\d{1,2})\D{0,20}(?:parallel\w*|parralel\w*|parralele|agenten|agents)",
        ]
        for pattern in patterns:
            match = re.search(pattern, lower)
            if match:
                return int(match.group(1))
        return None

    @staticmethod
    def _find_named_project(workspace: Path, name: str) -> Path | None:
        cleaned = name.strip().strip(".,;:!?").lower()
        if not cleaned:
            return None

        search_roots = []
        for root in (workspace, Path.cwd(), workspace.parent):
            resolved = root.expanduser().resolve()
            if resolved not in search_roots:
                search_roots.append(resolved)

        exact_matches: list[Path] = []
        fuzzy_matches: list[Path] = []
        for root in search_roots:
            try:
                children = [p for p in root.iterdir() if p.is_dir()]
            except OSError:
                continue
            for child in children:
                if child.name.lower() == cleaned:
                    exact_matches.append(child.resolve())
                elif cleaned in child.name.lower():
                    fuzzy_matches.append(child.resolve())
        if exact_matches:
            return exact_matches[0]
        unique_fuzzy = sorted(set(fuzzy_matches))
        return unique_fuzzy[0] if len(unique_fuzzy) == 1 else None

    @staticmethod
    def _explicit_project_name(args: str) -> str | None:
        patterns = [
            r"([A-Za-z0-9_.-]+)\s+(?:projekt|project)",
            r"(?:projekt|project)\s+([A-Za-z0-9_.-]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, args, re.IGNORECASE)
            if match:
                return match.group(1).strip().strip(".,;:!?")
        return None

    @staticmethod
    def _resolve_project_from_natural_args(
        args: str,
        positionals: list[str],
        agent: Agent,
    ) -> Path | None:
        workspace = SkillRunner._default_workspace(agent)
        lower = args.lower()

        for token in positionals:
            candidate = Path(token).expanduser()
            if candidate.exists() or "/" in token or token.startswith((".", "~")):
                return candidate.resolve()

        explicit_name = SkillRunner._explicit_project_name(args)
        if explicit_name:
            found = SkillRunner._find_named_project(workspace, explicit_name)
            if found:
                return found
            raise ValueError(
                f"Projekt '{explicit_name}' nicht eindeutig gefunden. Bitte Pfad explizit angeben."
            )

        for token in positionals:
            cleaned = token.strip().strip(".,;:!?")
            found = SkillRunner._find_named_project(workspace, cleaned)
            if found:
                return found

        # If a directory name appears in free text, use it even without explicit "project".
        for root in (workspace, Path.cwd(), workspace.parent):
            try:
                children = [p for p in root.expanduser().resolve().iterdir() if p.is_dir()]
            except OSError:
                continue
            for child in children:
                if child.name.lower() in lower:
                    return child.resolve()

        return None

    @staticmethod
    def _parse_herbert_swarm_args(args: str, agent: Agent) -> SimpleNamespace:
        tokens = shlex.split(args)
        project: str | None = None
        spec: str | None = None
        name: str | None = None
        parallel = 3
        timeout = 300
        dry_run = False
        retry_failed = False
        action = "full"
        positionals: list[str] = []

        actions = {"status", "report", "brain", "reset", "run", "plan", "init"}
        i = 0
        while i < len(tokens):
            token = tokens[i]
            normalized_token = token.strip().strip(".,;:!?").lower()
            if normalized_token in actions and action == "full":
                action = normalized_token
            elif token == "--dry-run":
                dry_run = True
            elif token == "--retry-failed":
                retry_failed = True
                action = "run"
            elif token == "--yes":
                pass
            elif token in {"--parallel", "-p"} and i + 1 < len(tokens):
                i += 1
                parallel = int(tokens[i])
            elif token in {"--timeout", "-t"} and i + 1 < len(tokens):
                i += 1
                timeout = int(tokens[i])
            elif token == "--name" and i + 1 < len(tokens):
                i += 1
                name = tokens[i]
            elif token == "--spec" and i + 1 < len(tokens):
                i += 1
                spec = tokens[i]
            elif token.startswith("-"):
                raise ValueError(f"Unbekannte Herbert-Swarm-Option: {token}")
            elif project is None and (
                Path(token).expanduser().exists() or "/" in token or token.startswith((".", "~"))
            ):
                project = token
            elif spec is None and token.lower().endswith((".md", ".txt")):
                spec = token
            else:
                positionals.append(token)
            i += 1

        natural_parallel = SkillRunner._extract_parallel_from_text(args)
        if natural_parallel is not None:
            parallel = natural_parallel

        natural_project = SkillRunner._resolve_project_from_natural_args(args, positionals, agent)
        if natural_project is not None and project is None:
            project = str(natural_project)

        project_path = (
            Path(project).expanduser().resolve()
            if project
            else SkillRunner._default_workspace(agent)
        )
        spec_path = Path(spec).expanduser().resolve() if spec else project_path / "SPEC.md"
        if parallel < 1:
            raise ValueError("--parallel muss mindestens 1 sein")
        if parallel > 12:
            raise ValueError("--parallel darf maximal 12 sein")
        if timeout < 1:
            raise ValueError("--timeout muss mindestens 1 Sekunde sein")

        return SimpleNamespace(
            action=action,
            project=str(project_path),
            spec=str(spec_path),
            name=name,
            parallel=parallel,
            timeout=timeout,
            dry_run=dry_run,
            retry_failed=retry_failed,
            yes="--yes" in tokens,
        )

    @staticmethod
    async def _run_herbert_swarm(args: str, session: Session, agent: Agent) -> str:
        if not args.strip() or "--help" in args:
            help_text = (
                "📖 **Herbert Swarm Hilfe**\n\n"
                "Der Swarm baut ganze Projekte für dich, indem er mehrere Agenten parallel einsetzt.\n\n"
                "**Einfachster Start:**\n"
                "- `/herbert-swarm . --dry-run` : KI-Plan erstellen und Ablauf prüfen, ohne Dateien zu ändern\n"
                "- `/herbert-swarm . --parallel 3` : Planen, ausführen und Bericht anzeigen\n\n"
                "**Befehle:**\n"
                "- `/herbert-swarm <pfad>` : Startet den vollen Zyklus (Init -> Plan -> Run -> Report)\n"
                "- `/herbert-swarm status`  : Zeigt den aktuellen Fortschritt\n"
                "- `/herbert-swarm run`     : Setzt die Ausführung fort\n"
                "- `/herbert-swarm reset`   : Löscht das Swarm-Brain des Projekts\n\n"
                "**Optionen:**\n"
                "- `--parallel N`  : Anzahl der Agenten (Standard: 3)\n"
                "- `--dry-run`     : Simuliert den Swarm ohne Dateien zu schreiben\n"
                "- `--spec <pfad>` : Pfad zu einer eigenen SPEC.md\n"
                "- `--retry-failed`: Nur fehlgeschlagene Tasks erneut versuchen\n\n"
                "**Nachvollziehbarkeit:**\n"
                "Nutze im Chat `/doctor`, `/what-now` und `/docs swarm`, wenn du den Zustand prüfen willst.\n"
            )
            session.add_assistant_message(help_text)
            return help_text

        try:
            parsed = SkillRunner._parse_herbert_swarm_args(args, agent)
        except Exception as exc:
            return f"Herbert Swarm: Ungueltige Argumente: {exc}"

        session.add_user_message(("/herbert-swarm " + args).strip())

        outputs: list[tuple[str, str]] = []

        try:
            swarm_tool = ToolRegistry.get("swarm")
            if swarm_tool is None:
                return "Herbert Swarm: ERROR: Das native swarm Tool ist nicht registriert."

            if parsed.action == "full":
                sequence = [
                    ("init", {"project": parsed.project, "name": parsed.name}),
                    ("plan", {"project": parsed.project, "spec": parsed.spec}),
                    (
                        "run",
                        {
                            "project": parsed.project,
                            "parallel": parsed.parallel,
                            "timeout": parsed.timeout,
                            "dry_run": parsed.dry_run,
                            "retry_failed": False,
                        },
                    ),
                    ("report", {"project": parsed.project}),
                ]
            elif parsed.action == "run":
                sequence = [
                    (
                        "run",
                        {
                            "project": parsed.project,
                            "parallel": parsed.parallel,
                            "timeout": parsed.timeout,
                            "dry_run": parsed.dry_run,
                            "retry_failed": parsed.retry_failed,
                        },
                    ),
                    ("report", {"project": parsed.project}),
                ]
            elif parsed.action == "plan":
                sequence = [("plan", {"project": parsed.project, "spec": parsed.spec})]
            elif parsed.action == "init":
                sequence = [("init", {"project": parsed.project, "name": parsed.name})]
            elif parsed.action == "reset":
                sequence = [("reset", {"project": parsed.project, "yes": parsed.yes})]
            else:
                sequence = [(parsed.action, {"project": parsed.project})]

            for command, kwargs in sequence:
                result = await swarm_tool.execute(command=command, **kwargs)
                output = (
                    result.output if result.success else "ERROR: " + (result.error or result.output)
                ).strip()
                outputs.append((command, output))
                if output.startswith("ERROR:"):
                    break
        except Exception as exc:
            outputs.append(("error", f"ERROR: {exc}"))

        lines = [f"Herbert Swarm: {parsed.project}"]
        for command, output in outputs:
            lines.append(f"- {command}: {output}")
        summary = "\n".join(lines)
        session.add_assistant_message(summary)
        return summary

    @staticmethod
    def _clean_response(content: str) -> str:
        """Clean the response by removing thinking blocks and verbose preambles."""
        # Remove thinking/reasoning blocks
        content = re.sub(
            r"<(think|thinking|thought)>(.*?)</\1>", "", content, flags=re.DOTALL | re.IGNORECASE
        ).strip()

        # Remove "Ich werde..." / "I will..." type preambles
        lines = content.split("\n")
        cleaned_lines: list[str] = []
        skip_mode = False
        for line in lines:
            stripped = line.strip().lower()
            if any(
                p in stripped
                for p in ["ich werde", "i will", "let me", "jetzt werde", "now i will", "i'll"]
            ):
                skip_mode = True
                continue
            if skip_mode and len(stripped) < 5:
                continue
            skip_mode = False
            cleaned_lines.append(line)

        return "\n".join(cleaned_lines).strip()

    @staticmethod
    async def run(skill: Skill, args: str, session: Session, agent: Agent) -> str:
        """Expand the skill prompt with `args` and run it through the agent.

        Returns the agent's response text (cleaned of thinking blocks and verbose
        preambles).  Handles tool calls by executing them and synthesizing results.
        Each step is guarded by `skill.timeout` seconds (default 30 s).
        """
        if skill.handler == "herbert_swarm":
            return await SkillRunner._run_herbert_swarm(args, session, agent)

        prompt = skill.prompt
        if not prompt and skill.steps:
            # Build a prompt from the steps list when no explicit prompt is set
            steps_text = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(skill.steps))
            prompt = f"Please follow these steps:\n{steps_text}"

        if "{args}" in prompt:
            prompt = prompt.replace("{args}", args.strip() or "(keine Argumente)")
        elif args.strip():
            # Append args if no placeholder defined
            prompt = f"{prompt}\n\nArgument: {args.strip()}"

        # Use run_with_tools to properly handle tool calls, wrapped in a timeout
        try:
            response = await asyncio.wait_for(
                agent.run_with_tools(session, prompt),
                timeout=skill.timeout,
            )
        except TimeoutError:
            return f"[Skill '{skill.name}' timed out after {skill.timeout}s]"

        # Process tool calls if any (but keep it simple to avoid MiniMax context issues)
        if response.tool_calls:
            # Execute all tool calls, add results to session so synthesize() works
            tool_results = []
            for tc in response.tool_calls:
                try:
                    result = await asyncio.wait_for(
                        ToolRegistry.execute(tc.name, **tc.arguments),
                        timeout=skill.timeout,
                    )
                except TimeoutError:
                    tool_results.append((tc.name, tc.id, f"[Tool '{tc.name}' timed out]"))
                    continue

                output_text = (
                    result.output if result.success else "ERROR: " + (result.error or result.output)
                )
                if len(output_text) > 3000:
                    output_text = (
                        output_text[:1500] + "\n... [TRUNCATED] ...\n" + output_text[-1500:]
                    )
                tool_results.append((tc.name, tc.id, output_text))

                # CRITICAL: add tool result to session so MiniMax doesn't get 400
                session.messages.append(
                    Message(
                        role=Role.TOOL,
                        content=output_text,
                        name=tc.name,
                        tool_call_id=tc.id,
                    )
                )

            results_summary = "\n\n".join(
                f"[TOOL: {name}] {output}" for name, _, output in tool_results
            )

            try:
                response_text = await asyncio.wait_for(
                    agent.synthesize(session),
                    timeout=skill.timeout,
                )
                raw = response_text or results_summary
            except TimeoutError:
                return f"[Synthesize timed out]\n\nTool-Ergebnisse:\n{results_summary}"
            except Exception as e:
                return f"[Error bei synthesize: {e}]\n\nTool-Ergebnisse:\n{results_summary}"

            return SkillRunner._clean_response(raw)

        raw = response.content or ""
        return SkillRunner._clean_response(raw)

    @staticmethod
    def list_skills(loader: SkillLoader) -> list[dict]:
        """Return a list of dicts describing all loaded skills.

        Each dict has keys: ``name``, ``command``, ``description``,
        ``args_hint``, ``steps``, ``timeout``.
        """
        return [
            {
                "name": skill.name,
                "command": skill.command,
                "description": skill.description,
                "args_hint": skill.args_hint,
                "steps": skill.steps,
                "timeout": skill.timeout,
            }
            for skill in loader.skills
        ]
