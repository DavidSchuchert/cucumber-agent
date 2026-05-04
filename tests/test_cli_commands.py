"""Tests for CLI slash command normalization and suggestions."""

from __future__ import annotations

from cucumber_agent.cli import (
    STATIC_SLASH_COMMANDS,
    _command_suggestion,
    _completion_commands,
    _resolve_skill_invocation,
)
from cucumber_agent.skills import SkillLoader


def test_resolve_skill_invocation_tolerates_punctuation(tmp_path):
    loader = SkillLoader(skills_dir=tmp_path, include_builtin=True)
    loader.load_all()

    skill, args = _resolve_skill_invocation(
        "/herbert-swarm. stelle Arcade fertig",
        loader,
    )

    assert skill.command == "/herbert-swarm"
    assert args == "stelle Arcade fertig"


def test_resolve_skill_invocation_supports_multi_word_alias(tmp_path):
    loader = SkillLoader(skills_dir=tmp_path, include_builtin=True)
    loader.load_all()

    skill, args = _resolve_skill_invocation(
        "/herbert swarm stelle Arcade fertig",
        loader,
    )

    assert skill.command == "/herbert-swarm"
    assert args == "stelle Arcade fertig"


def test_command_suggestion_for_typo(tmp_path):
    loader = SkillLoader(skills_dir=tmp_path, include_builtin=True)
    loader.load_all()

    suggestion = _command_suggestion("/ski", loader, STATIC_SLASH_COMMANDS)

    assert suggestion == "/skills"


def test_static_commands_include_autopilot():
    assert "/autopilot" in STATIC_SLASH_COMMANDS


def test_completion_commands_hide_skill_aliases(tmp_path):
    loader = SkillLoader(skills_dir=tmp_path, include_builtin=True)
    loader.load_all()

    commands = _completion_commands(loader)

    assert "/herbert-swarm" in commands
    assert "/herbert" not in commands
    assert "/herbert swarm" not in commands
    assert "/swarm" not in commands
