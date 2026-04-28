"""Skill runner — executes a skill by injecting its prompt into the agent."""

from __future__ import annotations

from typing import TYPE_CHECKING

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
        Returns the agent's response text.
        """
        prompt = skill.prompt
        if "{args}" in prompt:
            prompt = prompt.replace("{args}", args.strip() or "(keine Argumente)")
        elif args.strip():
            # Append args if no placeholder defined
            prompt = f"{prompt}\n\nArgument: {args.strip()}"

        return await agent.run(session, prompt)
