"""Tests for the native Agent Autopilot."""

from __future__ import annotations

import json

import pytest

from cucumber_agent.autopilot import (
    AutopilotStore,
    create_plan,
    parse_autopilot_args,
    report_text,
    run_plan,
    status_text,
    workspace_key,
)


def test_workspace_key_is_stable(tmp_path):
    assert workspace_key(tmp_path) == workspace_key(tmp_path)
    assert len(workspace_key(tmp_path)) == 16


def test_parse_autopilot_args_plan_and_run_options():
    planned = parse_autopilot_args("plan verbessere Arcade")
    assert planned.action == "plan"
    assert planned.goal == "verbessere Arcade"

    run = parse_autopilot_args("run --dry-run --parallel 4 --timeout 9")
    assert run.action == "run"
    assert run.dry_run is True
    assert run.parallel == 4
    assert run.timeout == 9


def test_parse_autopilot_args_rejects_bad_parallel():
    with pytest.raises(ValueError):
        parse_autopilot_args("run --parallel 0")


def test_create_plan_detects_python_project(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

    state = create_plan("mache das Projekt stabil", tmp_path)

    titles = [task.title for task in state.tasks]
    assert state.goal == "mache das Projekt stabil"
    assert "Python-Code und Schnittstellen verbessern" in titles
    assert "Python-Tests und Typchecks absichern" in titles


def test_autopilot_store_round_trip(tmp_path):
    state_dir = tmp_path / "state"
    workspace = tmp_path / "project"
    workspace.mkdir()
    store = AutopilotStore(workspace, state_dir)
    state = create_plan("baue v1", workspace)

    store.save(state)
    loaded = store.load()

    assert loaded is not None
    assert loaded.goal == "baue v1"
    assert loaded.workspace == str(workspace.resolve())
    assert store.path.parent == state_dir


def test_autopilot_store_handles_broken_json(tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    store = AutopilotStore(workspace, tmp_path / "state")
    store.path.parent.mkdir(parents=True)
    store.path.write_text("{", encoding="utf-8")

    assert store.load() is None


async def test_run_plan_dry_run_marks_pending_tasks_done(tmp_path):
    state = create_plan("teste dry-run", tmp_path)

    result = await run_plan(state, dry_run=True, parallel=2, timeout=5)

    assert all(task.status == "done" for task in result.tasks)
    assert all("DRY RUN" in task.result for task in result.tasks)
    assert "Autopilot Report" in result.last_report


def test_status_and_report_without_state_are_actionable():
    assert "/autopilot plan" in status_text(None)
    assert "/autopilot plan" in report_text(None)


def test_autopilot_store_reset(tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    store = AutopilotStore(workspace, tmp_path / "state")
    store.save(create_plan("reset me", workspace))

    assert store.reset() is True
    assert store.load() is None
    assert store.reset() is False


def test_saved_state_is_json_object(tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    store = AutopilotStore(workspace, tmp_path / "state")
    store.save(create_plan("json", workspace))

    payload = json.loads(store.path.read_text(encoding="utf-8"))

    assert payload["version"] == 1
    assert payload["goal"] == "json"
    assert isinstance(payload["tasks"], list)
