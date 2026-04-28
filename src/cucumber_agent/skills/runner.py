"""Skill runner — executes a skill by injecting its prompt into the agent."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from cucumber_agent.session import Message, Role
from cucumber_agent.tools import ToolRegistry

if TYPE_CHECKING:
    from cucumber_agent.agent import Agent
    from cucumber_agent.session import Session
    from cucumber_agent.skills.loader import Skill


class SkillRunner:
    """Runs a Skill by expanding its prompt template and sending it to the agent."""

    @staticmethod
    async def run(skill: Skill, args: str, session: Session, agent: Agent) -> str:
        """
        Expand the skill prompt with `args` and run it through the agent.
        Returns the agent's response text (cleaned of thinking blocks and verbose preambles).
        Handles tool calls by executing them and synthesizing results.
        """
        prompt = skill.prompt
        if "{args}" in prompt:
            prompt = prompt.replace("{args}", args.strip() or "(keine Argumente)")
        elif args.strip():
            # Append args if no placeholder defined
            prompt = f"{prompt}\n\nArgument: {args.strip()}"

        # Use run_with_tools to properly handle tool calls
        response = await agent.run_with_tools(session, prompt)

        # Process tool calls if any (but keep it simple to avoid MiniMax context issues)
        if response.tool_calls:
            # Execute all tool calls and collect results
            tool_results = []
            for tc in response.tool_calls:
                result = await ToolRegistry.execute(tc.name, **tc.arguments)
                output_text = result.output if result.success else 'ERROR: ' + (result.error or result.output)
                if len(output_text) > 3000:
                    output_text = output_text[:1500] + "\n... [TRUNCATED] ...\n" + output_text[-1500:]
                tool_results.append((tc.name, tc.id, output_text))

            # Build a summary of all tool results
            results_lines = [f"[TOOL: {name}] {output}" for name, _, output in tool_results]
            results_summary = "\n\n".join(results_lines)

            # Ask the model to synthesize a response using synthesize() which disables tools
            synthesize_prompt = (
                f"Du hast folgende Werkzeuge ausgeführt:\n{results_summary}\n\n"
                f"Gib dem Benutzer eine klare, prägnante Antwort. Keine weiteren Werkzeug-Aufrufe."
            )

            try:
                response_text = await agent.synthesize(session, synthesize_prompt)
                return response_text
            except Exception as e:
                return f"[Error bei synthesize: {e}]\n\nTool-Ergebnisse:\n{results_summary}"

        return response.content or ""

    @staticmethod
    def _clean_response(content: str) -> str:
        """Clean the response by removing thinking blocks and verbose preambles."""
        # Remove thinking/reasoning blocks
        content = re.sub(
            r'<(think|thinking|thought)>(.*?)</\1>',
            '',
            content,
            flags=re.DOTALL | re.IGNORECASE
        ).strip()

        # Remove "Ich werde..." / "I will..." type preambles
        lines = content.split('\n')
        cleaned_lines = []
        skip_mode = False
        for line in lines:
            stripped = line.strip().lower()
            if any(p in stripped for p in ['ich werde', 'i will', 'let me', 'jetzt werde', 'now i will', 'i\'ll']):
                skip_mode = True
                continue
            if skip_mode and len(stripped) < 5:
                continue
            skip_mode = False
            cleaned_lines.append(line)

        return '\n'.join(cleaned_lines).strip()
