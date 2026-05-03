"""Skill runner — executes a skill by injecting its prompt into the agent."""

from __future__ import annotations

import asyncio
import re
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
