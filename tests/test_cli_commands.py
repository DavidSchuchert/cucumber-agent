"""Tests for CLI slash command normalization and suggestions."""

from __future__ import annotations

import subprocess

import pytest

from cucumber_agent.cli import (
    SLASH_COMMAND_ALIASES,
    STATIC_SLASH_COMMANDS,
    _canonical_slash_command,
    _command_suggestion,
    _completion_commands,
    _doc_topic_map,
    _get_install_dir,
    _read_doc_excerpt,
    _resolve_skill_invocation,
    get_git_behind_count,
    get_git_short_revision,
)
from cucumber_agent.config import Config
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


def test_static_commands_include_ux_helpers():
    for command in {
        "/quickstart",
        "/shortcuts",
        "/spec-template",
        "/doctor",
        "/tips",
        "/examples",
        "/what-now",
        "/docs",
        "/explain-last",
    }:
        assert command in STATIC_SLASH_COMMANDS


def test_slash_aliases_are_canonicalized():
    assert _canonical_slash_command("/?") == "/help"
    assert _canonical_slash_command("/start") == "/quickstart"
    assert _canonical_slash_command("/next") == "/what-now"
    assert _canonical_slash_command("/why") == "/explain-last"
    assert SLASH_COMMAND_ALIASES["/cheatsheet"] == "/examples"
    assert SLASH_COMMAND_ALIASES["/spec"] == "/spec-template"


def test_completion_commands_hide_skill_aliases(tmp_path):
    loader = SkillLoader(skills_dir=tmp_path, include_builtin=True)
    loader.load_all()

    commands = _completion_commands(loader)

    assert "/herbert-swarm" in commands
    assert "/herbert" not in commands
    assert "/herbert swarm" not in commands
    assert "/swarm" not in commands


def test_run_update_uses_configured_install_dir(tmp_path, monkeypatch):
    from cucumber_agent import cli

    install_dir = tmp_path / "custom-install"
    update_script = install_dir / "installer" / "update.sh"
    update_script.parent.mkdir(parents=True)
    update_script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))

        class Result:
            returncode = 7

        return Result()

    monkeypatch.setenv("CUCUMBER_INSTALL_DIR", str(install_dir))
    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(SystemExit) as exc:
        cli.run_update()

    assert exc.value.code == 7
    assert calls[0][0] == [str(update_script)]
    assert calls[0][1]["cwd"] == install_dir


def test_get_install_dir_respects_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CUCUMBER_INSTALL_DIR", str(tmp_path))

    assert _get_install_dir() == str(tmp_path.resolve())


def test_get_git_behind_count_reads_left_side_as_behind(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()

    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(args)

        class Result:
            returncode = 0
            stdout = "2\t0\n"

        return Result()

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert get_git_behind_count(str(tmp_path)) == 2
    assert calls[-1] == ["git", "rev-list", "--count", "--left-right", "@{upstream}...HEAD"]


def test_get_git_short_revision(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()

    def fake_run(args, **kwargs):
        class Result:
            returncode = 0
            stdout = "abc1234\n"

        return Result()

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert get_git_short_revision(str(tmp_path)) == "abc1234"


def test_docs_topic_map_and_excerpt(tmp_path, monkeypatch):
    install_dir = tmp_path / "install"
    wiki = install_dir / "wiki"
    wiki.mkdir(parents=True)
    (wiki / "Swarm.md").write_text("# Swarm\n\nKurzinfo\n\nMehr Details\n", encoding="utf-8")
    monkeypatch.setenv("CUCUMBER_INSTALL_DIR", str(install_dir))

    assert _doc_topic_map()["herbert"] == "Swarm.md"
    assert _doc_topic_map()["spec"] == "Swarm.md"
    doc = _read_doc_excerpt(Config(), "herbert")

    assert doc is not None
    title, excerpt, path = doc
    assert title == "Swarm"
    assert "Kurzinfo" in excerpt
    assert path == wiki / "Swarm.md"
