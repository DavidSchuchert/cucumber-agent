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
        Handles tool calls properly by feeding results back until the task is complete.
        """
        prompt = skill.prompt
        if "{args}" in prompt:
            prompt = prompt.replace("{args}", args.strip() or "(keine Argumente)")
        elif args.strip():
            # Append args if no placeholder defined
            prompt = f"{prompt}\n\nArgument: {args.strip()}"

        # Use run_with_tools to properly handle tool calls
        response = await agent.run_with_tools(session, prompt)

        # Process tool calls if any (recursive reasoning loop)
        loop_count = 0
        max_loops = 10
        while response.tool_calls and loop_count < max_loops:
            loop_count += 1
            for tc in response.tool_calls:
                # Skills execute tools AUTOMATICALLY (no approval)
                result = await ToolRegistry.execute(tc.name, **tc.arguments)

                output_text = result.output if result.success else 'ERROR: ' + (result.error or result.output)
                if len(output_text) > 3000:
                    output_text = output_text[:1500] + "\n... [TRUNCATED] ...\n" + output_text[-1500:]

                tool_result_msg = Message(
                    role=Role.TOOL,
                    content=output_text,
                    name=tc.name,
                    tool_call_id=tc.id
                )
                session.messages.append(tool_result_msg)

            # Let agent continue with tool results
            response = await agent.run_with_tools(session, "")

        # Clean the final response
        content = response.content or ""

        # Remove thinking/reasoning blocks
        content = re.sub(r'<(think|thinking|thought)>(.*?)</\1>', '', content, flags=re.DOTALL | re.IGNORECASE).strip()

        # Remove "Ich werde..." / "I will..." type preambles (model talking about what it will do)
        lines = content.split('\n')
        cleaned_lines = []
        skip_mode = False
        for line in lines:
            stripped = line.strip().lower()
            # Skip lines that are just "Ich werde..." or "I will..." type preambles
            if any(p in stripped for p in ['ich werde', 'i will', 'let me', 'jetzt werde', 'now i will', 'i\'ll']):
                skip_mode = True
                continue
            # Skip very short lines that are likely preambles
            if skip_mode and len(stripped) < 5:
                continue
            skip_mode = False
            cleaned_lines.append(line)

        content = '\n'.join(cleaned_lines).strip()

        return content
