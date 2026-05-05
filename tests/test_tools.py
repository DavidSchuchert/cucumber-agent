"""Tests for the cucumber-agent tool system."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

# ── Calculator ───────────────────────────────────────────────────────────────
from cucumber_agent.tools.agent import (
    _public_progress_note,
    _result_preview,
    _tool_stage_summary,
)
from cucumber_agent.tools.base import BaseTool, ToolResult
from cucumber_agent.tools.calculator import CalculatorTool, safe_calculate
from cucumber_agent.tools.datetime_tool import DatetimeTool
from cucumber_agent.tools.loader import CustomToolLoader
from cucumber_agent.tools.read_file import ReadFileTool
from cucumber_agent.tools.registry import ToolRegistry
from cucumber_agent.tools.remember import RememberTool
from cucumber_agent.tools.swarm import SwarmTool
from cucumber_agent.tools.write_file import WriteFileTool


class TestSafeCalculate:
    """Unit tests for the safe_calculate() function."""

    def test_basic_addition(self):
        assert safe_calculate("2 + 3") == pytest.approx(5.0)

    def test_basic_subtraction(self):
        assert safe_calculate("10 - 4") == pytest.approx(6.0)

    def test_multiplication(self):
        assert safe_calculate("3 * 7") == pytest.approx(21.0)

    def test_division(self):
        assert safe_calculate("10 / 4") == pytest.approx(2.5)

    def test_floor_division(self):
        assert safe_calculate("10 // 3") == pytest.approx(3.0)

    def test_modulo(self):
        assert safe_calculate("10 % 3") == pytest.approx(1.0)

    def test_power(self):
        assert safe_calculate("2 ** 10") == pytest.approx(1024.0)

    def test_negative_unary(self):
        assert safe_calculate("-5 + 3") == pytest.approx(-2.0)

    def test_positive_unary(self):
        assert safe_calculate("+5") == pytest.approx(5.0)

    def test_nested_expression(self):
        assert safe_calculate("(2 + 3) * (4 - 1)") == pytest.approx(15.0)

    def test_sqrt(self):
        assert safe_calculate("sqrt(4)") == pytest.approx(2.0)

    def test_sqrt_non_perfect(self):
        assert safe_calculate("sqrt(2)") == pytest.approx(1.41421356, rel=1e-6)

    def test_sin_pi_over_2(self):
        assert safe_calculate("sin(pi / 2)") == pytest.approx(1.0)

    def test_cos_zero(self):
        assert safe_calculate("cos(0)") == pytest.approx(1.0)

    def test_pi_constant(self):
        import math

        assert safe_calculate("pi") == pytest.approx(math.pi)

    def test_e_constant(self):
        import math

        assert safe_calculate("e") == pytest.approx(math.e)

    def test_log_base_e(self):
        assert safe_calculate("log(e)") == pytest.approx(1.0)

    def test_abs_negative(self):
        assert safe_calculate("abs(-42)") == pytest.approx(42.0)

    def test_floor(self):
        assert safe_calculate("floor(3.9)") == pytest.approx(3.0)

    def test_ceil(self):
        assert safe_calculate("ceil(3.1)") == pytest.approx(4.0)

    def test_factorial(self):
        assert safe_calculate("factorial(5)") == pytest.approx(120.0)

    def test_combined_expression(self):
        # sqrt(3^2 + 4^2) = 5
        assert safe_calculate("sqrt(3**2 + 4**2)") == pytest.approx(5.0)

    # ── Error cases ──────────────────────────────────────────────────────────

    def test_division_by_zero(self):
        with pytest.raises(ValueError, match="[Dd]ivision by zero"):
            safe_calculate("1 / 0")

    def test_unknown_name(self):
        with pytest.raises(ValueError, match="Unknown name"):
            safe_calculate("x + 1")

    def test_unknown_function(self):
        with pytest.raises(ValueError, match="Unknown function"):
            safe_calculate("eval('1')")

    def test_disallowed_operator_bitwise(self):
        with pytest.raises((ValueError, SyntaxError)):
            safe_calculate("1 & 2")

    def test_empty_expression(self):
        with pytest.raises(ValueError, match="Empty expression"):
            safe_calculate("")

    def test_string_literal_rejected(self):
        with pytest.raises(ValueError):
            safe_calculate("'hello'")

    def test_builtin_import_rejected(self):
        with pytest.raises(ValueError):
            safe_calculate("__import__('os')")

    def test_too_long_expression(self):
        with pytest.raises(ValueError, match="too long"):
            safe_calculate("1 + " * 200)


@pytest.mark.asyncio
class TestCalculatorTool:
    """Integration tests for the CalculatorTool."""

    async def test_simple_calculation(self):
        tool = CalculatorTool()
        result = await tool.execute(expression="2 + 2")
        assert result.success is True
        assert "4" in result.output

    async def test_integer_result_formatted_without_decimal(self):
        tool = CalculatorTool()
        result = await tool.execute(expression="10 / 2")
        assert result.success is True
        assert "5" in result.output
        assert "5.0" not in result.output  # Should be "5", not "5.0"

    async def test_float_result(self):
        tool = CalculatorTool()
        result = await tool.execute(expression="1 / 3")
        assert result.success is True
        assert "0.333" in result.output

    async def test_error_returns_failure(self):
        tool = CalculatorTool()
        result = await tool.execute(expression="1 / 0")
        assert result.success is False
        assert result.error is not None

    async def test_expression_in_output(self):
        """Output should show the original expression alongside the result."""
        tool = CalculatorTool()
        result = await tool.execute(expression="3 * 3")
        assert result.success is True
        assert "3 * 3" in result.output
        assert "9" in result.output


@pytest.mark.asyncio
class TestSwarmTool:
    async def test_full_dry_run_path(self, tmp_path, monkeypatch):
        from cucumber_agent.tools import swarm as swarm_module

        (tmp_path / "SPEC.md").write_text(
            "Build a FastAPI backend with SQLite database and pytest tests.",
            encoding="utf-8",
        )

        async def fake_llm_plan(spec_content, project_path):
            return {
                "phases": ["DATABASE", "BACKEND", "TESTING"],
                "tasks": [
                    {
                        "id": "db",
                        "description": "Create SQLite persistence layer",
                        "agent_role": "coder",
                        "phase": "DATABASE",
                        "priority": 1,
                        "files": ["backend/database.py"],
                        "dependencies": [],
                    },
                    {
                        "id": "api",
                        "description": "Create FastAPI application routes",
                        "agent_role": "coder",
                        "phase": "BACKEND",
                        "priority": 2,
                        "files": ["backend/server.py"],
                        "dependencies": ["db"],
                    },
                    {
                        "id": "tests",
                        "description": "Create pytest coverage for the API",
                        "agent_role": "tester",
                        "phase": "TESTING",
                        "priority": 3,
                        "files": ["tests/test_api.py"],
                        "dependencies": ["api"],
                    },
                ],
                "reasoning": "Backend, database, and tests are requested.",
            }

        monkeypatch.setattr(swarm_module, "_llm_create_task_plan", fake_llm_plan)

        tool = SwarmTool()

        init = await tool.execute(command="init", project=str(tmp_path))
        plan = await tool.execute(command="plan", project=str(tmp_path))
        run = await tool.execute(command="run", project=str(tmp_path), dry_run=True)
        report = await tool.execute(command="report", project=str(tmp_path))

        assert init.success is True
        assert plan.success is True
        assert "Plan:" in plan.output
        assert run.success is True
        assert "Swarm complete" in run.output
        assert report.success is True
        assert "Report:" in report.output
        brain = json.loads((tmp_path / ".swarm_brain.json").read_text(encoding="utf-8"))
        assert "FRONTEND" not in brain["phases"]
        assert brain["phases"] == ["DATABASE", "BACKEND", "TESTING"]
        assert brain["tasks"]["task-002"]["dependencies"] == ["task-001"]

    async def test_run_rejects_invalid_parallel(self, tmp_path):
        tool = SwarmTool()
        result = await tool.execute(command="run", project=str(tmp_path), parallel=0)

        assert result.success is True
        assert result.output.startswith("ERROR:")

    async def test_run_uses_async_tasks_without_thread_event_loops(self, tmp_path, monkeypatch):
        from cucumber_agent.tools import swarm as swarm_module

        tool = SwarmTool()
        await tool.execute(command="init", project=str(tmp_path))
        brain_file = tmp_path / ".swarm_brain.json"
        brain = json.loads(brain_file.read_text(encoding="utf-8"))
        brain["phases"] = ["IMPLEMENTATION"]
        brain["tasks"] = {
            f"task-{i:03d}": {
                "id": f"task-{i:03d}",
                "description": f"Task {i}",
                "agent_role": "coder",
                "files": [],
                "dependencies": [],
                "status": "pending",
                "priority": i,
                "phase": 1,
                "created_by": "test",
            }
            for i in range(1, 4)
        }
        brain_file.write_text(json.dumps(brain), encoding="utf-8")

        loop_ids = set()

        async def fake_run_task(tid, task, brain, brain_file):
            import asyncio

            loop_ids.add(id(asyncio.get_running_loop()))
            await asyncio.sleep(0)
            return {"success": True, "output": f"done {tid}"}

        monkeypatch.setattr(swarm_module, "_run_task_async", fake_run_task)

        result = await tool.execute(command="run", project=str(tmp_path), parallel=3)

        assert result.success is True
        assert "3/3 tasks done" in result.output
        assert len(loop_ids) == 1

    async def test_run_does_not_close_shared_provider_between_tasks(self, tmp_path, monkeypatch):
        from types import SimpleNamespace

        from cucumber_agent.agent import Agent
        from cucumber_agent.config import Config
        from cucumber_agent.tools.swarm import _run_task_async

        class FakeProvider:
            def __init__(self):
                self.closed = False

            async def close(self):
                self.closed = True

        class FakeAgent:
            def __init__(self, provider):
                self._provider = provider

            async def run_with_tools(self, session, current_input):
                return SimpleNamespace(tool_calls=None, content="done")

        provider = FakeProvider()
        monkeypatch.setattr(
            Config,
            "load",
            staticmethod(lambda: SimpleNamespace(agent=SimpleNamespace(model="fake"))),
        )
        monkeypatch.setattr(
            Agent, "from_config", classmethod(lambda cls, config: FakeAgent(provider))
        )

        result = await _run_task_async(
            "task-001",
            {
                "id": "task-001",
                "description": "Task 1",
                "agent_role": "coder",
                "files": [],
            },
            {"project_path": str(tmp_path), "spec_summary": ""},
            tmp_path / ".swarm_brain.json",
        )

        assert result == {"success": True, "output": "done"}
        assert provider.closed is False

    async def test_run_stores_structured_failure_details(self, tmp_path, monkeypatch):
        from cucumber_agent.tools import swarm as swarm_module

        tool = SwarmTool()
        await tool.execute(command="init", project=str(tmp_path))
        brain_file = tmp_path / ".swarm_brain.json"
        brain = json.loads(brain_file.read_text(encoding="utf-8"))
        brain["phases"] = ["IMPLEMENTATION"]
        brain["tasks"] = {
            "task-001": {
                "id": "task-001",
                "description": "Failing task",
                "agent_role": "coder",
                "files": [],
                "dependencies": [],
                "status": "pending",
                "priority": 1,
                "phase": 1,
                "created_by": "test",
            }
        }
        brain_file.write_text(json.dumps(brain), encoding="utf-8")

        async def fake_run_task(tid, task, brain, brain_file):
            return {
                "success": False,
                "error_type": "ToolExecutionError",
                "tool_name": "shell",
                "message": "Tool failed without stderr/output",
            }

        monkeypatch.setattr(swarm_module, "_run_task_async", fake_run_task)

        result = await tool.execute(command="run", project=str(tmp_path))

        assert result.success is True
        brain = json.loads(brain_file.read_text(encoding="utf-8"))
        task = brain["tasks"]["task-001"]
        assert task["status"] == "failed"
        assert "ToolExecutionError" in task["error"]
        assert task["error_details"]["tool_name"] == "shell"

    async def test_ci_only_spec_gets_implementation_task(self, tmp_path, monkeypatch):
        from cucumber_agent.tools import swarm as swarm_module

        (tmp_path / "SPEC.md").write_text(
            "Create a tiny project README for a smoke test. Keep it simple, "
            "write only README.md, and include one short usage section.",
            encoding="utf-8",
        )

        async def fake_llm_failure(spec_content, project_path):
            raise RuntimeError("planner unavailable")

        monkeypatch.setattr(swarm_module, "_llm_create_task_plan", fake_llm_failure)

        tool = SwarmTool()

        await tool.execute(command="init", project=str(tmp_path))
        result = await tool.execute(command="plan", project=str(tmp_path))

        assert result.success is True
        brain = json.loads((tmp_path / ".swarm_brain.json").read_text(encoding="utf-8"))
        tasks = list(brain["tasks"].values())
        assert len(tasks) == 1
        assert tasks[0]["description"] == "Implement the project requirements described in SPEC.md"
        assert brain["phases"] == ["IMPLEMENTATION"]

    async def test_ai_plan_sanitizes_invalid_files_and_roles(self, tmp_path, monkeypatch):
        from cucumber_agent.tools import swarm as swarm_module

        async def fake_llm_plan(spec_content, project_path):
            return {
                "phases": ["implementation"],
                "tasks": [
                    {
                        "id": "main",
                        "description": "Write the app",
                        "agent_role": "wizard",
                        "phase": "implementation",
                        "priority": "high",
                        "files": ["app.py", "../outside.txt", "/tmp/nope"],
                        "dependencies": ["missing"],
                    }
                ],
            }

        monkeypatch.setattr(swarm_module, "_llm_create_task_plan", fake_llm_plan)

        tool = SwarmTool()
        await tool.execute(command="init", project=str(tmp_path))
        result = await tool.execute(command="plan", project=str(tmp_path))

        assert result.success is True
        brain = json.loads((tmp_path / ".swarm_brain.json").read_text(encoding="utf-8"))
        task = brain["tasks"]["task-001"]
        assert task["agent_role"] == "coder"
        assert task["files"] == ["app.py"]
        assert task["dependencies"] == []

    async def test_swarm_tool_args_block_write_outside_project(self, tmp_path):
        from cucumber_agent.tools.swarm import _normalize_swarm_tool_args

        args, failure = _normalize_swarm_tool_args(
            "write_file",
            {"path": str(tmp_path.parent / "outside.txt"), "content": "x"},
            tmp_path,
        )

        assert args is None
        assert failure is not None
        assert failure["error_type"] == "PathSafetyError"


# ── Datetime Tool ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestDatetimeTool:
    """Tests for the DatetimeTool."""

    async def test_returns_current_time_local(self):
        tool = DatetimeTool()
        result = await tool.execute()
        assert result.success is True
        assert "ISO-8601" in result.output

    async def test_utc_timezone(self):
        tool = DatetimeTool()
        result = await tool.execute(timezone="UTC")
        assert result.success is True
        assert "UTC" in result.output

    async def test_cet_timezone(self):
        tool = DatetimeTool()
        result = await tool.execute(timezone="CET")
        assert result.success is True
        assert result.error is None

    async def test_jst_timezone(self):
        tool = DatetimeTool()
        result = await tool.execute(timezone="JST")
        assert result.success is True

    async def test_unknown_timezone_returns_error(self):
        tool = DatetimeTool()
        result = await tool.execute(timezone="NOTREAL")
        assert result.success is False
        assert "Unknown timezone" in (result.error or "")

    async def test_custom_format(self):
        tool = DatetimeTool()
        result = await tool.execute(timezone="UTC", format="%Y-%m-%d")
        assert result.success is True
        # Should contain a date in YYYY-MM-DD form
        import re

        assert re.search(r"\d{4}-\d{2}-\d{2}", result.output)

    async def test_iana_timezone_if_available(self):
        """Test IANA timezone names work when zoneinfo is available."""
        try:
            from zoneinfo import ZoneInfo  # noqa: F401

            tool = DatetimeTool()
            result = await tool.execute(timezone="Europe/Berlin")
            assert result.success is True
        except ImportError:
            pytest.skip("zoneinfo not available")


# ── ReadFileTool ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestReadFileTool:
    """Tests for the ReadFileTool."""

    async def test_reads_existing_file(self, tmp_path):
        f = tmp_path / "hello.txt"
        f.write_text("Hello, World!", encoding="utf-8")
        tool = ReadFileTool()
        result = await tool.execute(path=str(f))
        assert result.success is True
        assert "Hello, World!" in result.output

    async def test_missing_file_returns_error(self, tmp_path):
        tool = ReadFileTool()
        result = await tool.execute(path=str(tmp_path / "nonexistent.txt"))
        assert result.success is False
        assert result.error is not None

    async def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("", encoding="utf-8")
        tool = ReadFileTool()
        result = await tool.execute(path=str(f))
        assert result.success is True
        assert result.output == ""

    async def test_truncation_at_max_lines(self, tmp_path):
        f = tmp_path / "long.txt"
        f.write_text("\n".join(f"line {i}" for i in range(100)), encoding="utf-8")
        tool = ReadFileTool()
        result = await tool.execute(path=str(f), max_lines=10)
        assert result.success is True
        assert "abgeschnitten" in result.output  # truncation notice in German
        assert "line 9" in result.output
        assert "line 10" not in result.output.split("abgeschnitten")[0]

    async def test_binary_like_content_with_replace_errors(self, tmp_path):
        """Verify binary-ish files don't crash — errors='replace' used."""
        f = tmp_path / "binary.bin"
        f.write_bytes(b"\xff\xfe hello \x00\x01")
        tool = ReadFileTool()
        result = await tool.execute(path=str(f))
        # Should succeed (replacement chars) or succeed
        assert result.success is True

    async def test_directory_path_returns_error(self, tmp_path):
        tool = ReadFileTool()
        result = await tool.execute(path=str(tmp_path))
        assert result.success is False
        assert result.error is not None


# ── WriteFileTool ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestWriteFileTool:
    """Tests for the WriteFileTool."""

    async def test_creates_new_file(self, tmp_path):
        tool = WriteFileTool()
        dest = tmp_path / "out.txt"
        result = await tool.execute(path=str(dest), content="test content")
        assert result.success is True
        assert dest.read_text(encoding="utf-8") == "test content"

    async def test_overwrites_existing_file(self, tmp_path):
        dest = tmp_path / "out.txt"
        dest.write_text("old content", encoding="utf-8")
        tool = WriteFileTool()
        result = await tool.execute(path=str(dest), content="new content")
        assert result.success is True
        assert dest.read_text(encoding="utf-8") == "new content"

    async def test_append_mode(self, tmp_path):
        dest = tmp_path / "out.txt"
        dest.write_text("first\n", encoding="utf-8")
        tool = WriteFileTool()
        result = await tool.execute(path=str(dest), content="second\n", mode="append")
        assert result.success is True
        assert dest.read_text(encoding="utf-8") == "first\nsecond\n"

    async def test_creates_parent_directories(self, tmp_path):
        dest = tmp_path / "a" / "b" / "c" / "out.txt"
        tool = WriteFileTool()
        result = await tool.execute(path=str(dest), content="deep content")
        assert result.success is True
        assert dest.exists()

    async def test_empty_content_allowed(self, tmp_path):
        dest = tmp_path / "empty.txt"
        tool = WriteFileTool()
        result = await tool.execute(path=str(dest), content="")
        assert result.success is True
        assert dest.read_text(encoding="utf-8") == ""


# ── RememberTool ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestRememberTool:
    """Tests for the RememberTool."""

    async def test_stores_fact(self, tmp_path):
        facts_file = tmp_path / "facts.json"
        tool = RememberTool()
        # Patch the module-level _FACTS_FILE path
        with patch("cucumber_agent.tools.remember._FACTS_FILE", facts_file):
            result = await tool.execute(key="name", value="David")
        assert result.success is True
        data = json.loads(facts_file.read_text(encoding="utf-8"))
        assert data.get("name") == "David"

    async def test_normalizes_key(self, tmp_path):
        facts_file = tmp_path / "facts.json"
        tool = RememberTool()
        with patch("cucumber_agent.tools.remember._FACTS_FILE", facts_file):
            result = await tool.execute(key="My Project", value="CucumberAgent")
        assert result.success is True
        data = json.loads(facts_file.read_text(encoding="utf-8"))
        assert "my_project" in data

    async def test_updates_existing_key(self, tmp_path):
        facts_file = tmp_path / "facts.json"
        tool = RememberTool()
        with patch("cucumber_agent.tools.remember._FACTS_FILE", facts_file):
            await tool.execute(key="lang", value="Python")
            await tool.execute(key="lang", value="Rust")
        data = json.loads(facts_file.read_text(encoding="utf-8"))
        assert data["lang"] == "Rust"

    async def test_preserves_existing_facts(self, tmp_path):
        facts_file = tmp_path / "facts.json"
        facts_file.write_text(json.dumps({"city": "Berlin"}), encoding="utf-8")
        tool = RememberTool()
        with patch("cucumber_agent.tools.remember._FACTS_FILE", facts_file):
            await tool.execute(key="name", value="David")
        data = json.loads(facts_file.read_text(encoding="utf-8"))
        assert data["city"] == "Berlin"
        assert data["name"] == "David"


# ── ToolRegistry ─────────────────────────────────────────────────────────────


class _DummyTool(BaseTool):
    name = "dummy_test_tool"
    description = "A dummy tool for testing"
    parameters = {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, output="dummy")


class TestToolRegistry:
    """Tests for the ToolRegistry."""

    def setup_method(self):
        """Ensure the dummy tool is unregistered before each test."""
        ToolRegistry.unregister("dummy_test_tool")

    def teardown_method(self):
        ToolRegistry.unregister("dummy_test_tool")

    def test_register_and_get(self):
        tool = _DummyTool()
        ToolRegistry.register(tool)
        assert ToolRegistry.get("dummy_test_tool") is tool

    def test_unregister(self):
        tool = _DummyTool()
        ToolRegistry.register(tool)
        ToolRegistry.unregister("dummy_test_tool")
        assert ToolRegistry.get("dummy_test_tool") is None

    def test_list_includes_registered_tool(self):
        tool = _DummyTool()
        ToolRegistry.register(tool)
        assert "dummy_test_tool" in ToolRegistry.list_tools()

    def test_get_unknown_tool_returns_none(self):
        assert ToolRegistry.get("this_does_not_exist_xyz") is None

    def test_re_register_replaces_old_instance(self):
        """Re-registering a tool by same name replaces it (no duplicates)."""
        tool1 = _DummyTool()
        tool2 = _DummyTool()
        ToolRegistry.register(tool1)
        count_before = ToolRegistry.list_tools().count("dummy_test_tool")
        ToolRegistry.register(tool2)
        count_after = ToolRegistry.list_tools().count("dummy_test_tool")
        assert count_before == 1
        assert count_after == 1
        assert ToolRegistry.get("dummy_test_tool") is tool2

    @pytest.mark.asyncio
    async def test_execute_unknown_tool_returns_error(self):
        result = await ToolRegistry.execute("definitely_not_a_real_tool_xyz")
        assert result.success is False
        assert "Unknown tool" in (result.error or "")

    @pytest.mark.asyncio
    async def test_execute_registered_tool(self):
        ToolRegistry.register(_DummyTool())
        result = await ToolRegistry.execute("dummy_test_tool")
        assert result.success is True
        assert result.output == "dummy"

    def test_get_tools_spec_contains_registered(self):
        ToolRegistry.register(_DummyTool())
        specs = ToolRegistry.get_tools_spec()
        names = [s["function"]["name"] for s in specs]
        assert "dummy_test_tool" in names


class TestAgentToolProgressDisplay:
    """Tests for the sub-agent progress display helpers."""

    def test_tool_stage_summary_uses_tool_reason(self):
        tool_call = SimpleNamespace(
            name="shell",
            arguments={"command": "python build_audio.py", "reason": "Audio-Bibliotheken prüfen"},
        )

        assert _tool_stage_summary([tool_call]) == "shell: Audio-Bibliotheken prüfen"

    def test_public_progress_note_is_short_single_line(self):
        note = _public_progress_note(
            "Ich prüfe zuerst, welche Audio-Tools lokal verfügbar sind.\n"
            "Danach erstelle ich den Track."
        )

        assert note == "Ich prüfe zuerst, welche Audio-Tools lokal verfügbar sind."

    def test_result_preview_collapses_output(self):
        result = ToolResult(success=True, output="numpy OK\n/usr/bin/ffmpeg\n")

        assert _result_preview(result) == "numpy OK /usr/bin/ffmpeg"


# ── CustomToolLoader hot-reload ───────────────────────────────────────────────


class TestCustomToolLoader:
    """Tests for hot-reload behaviour in CustomToolLoader."""

    def _write_tool(self, path: Path, tool_name: str) -> None:
        path.write_text(
            f"""\
from cucumber_agent.tools.base import BaseTool, ToolResult
from cucumber_agent.tools.registry import ToolRegistry

class _Hot{tool_name.title()}Tool(BaseTool):
    name = "{tool_name}"
    description = "hot reload test"
    parameters = {{"type": "object", "properties": {{}}, "required": []}}

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, output="{tool_name}")

ToolRegistry.register(_Hot{tool_name.title()}Tool())
""",
            encoding="utf-8",
        )

    def teardown_method(self):
        for name in ("hot_tool_a", "hot_tool_b"):
            ToolRegistry.unregister(name)

    def test_load_all_registers_tool(self, tmp_path):
        self._write_tool(tmp_path / "tool_a.py", "hot_tool_a")
        loader = CustomToolLoader(tools_dir=tmp_path)
        loader.load_all()
        assert ToolRegistry.get("hot_tool_a") is not None

    def test_load_all_unregisters_deleted_tool(self, tmp_path):
        f = tmp_path / "tool_a.py"
        self._write_tool(f, "hot_tool_a")
        loader = CustomToolLoader(tools_dir=tmp_path)
        loader.load_all()
        assert ToolRegistry.get("hot_tool_a") is not None

        # Delete the file and reload
        f.unlink()
        loader.load_all()
        assert ToolRegistry.get("hot_tool_a") is None

    def test_reload_replaces_not_duplicates(self, tmp_path):
        """After a file changes, re-loading must not duplicate the tool."""
        f = tmp_path / "tool_a.py"
        self._write_tool(f, "hot_tool_a")
        loader = CustomToolLoader(tools_dir=tmp_path)
        loader.load_all()

        # Simulate a mtime change by touching the file
        import time

        time.sleep(0.01)
        f.touch()

        loader.load_all()
        # Tool should appear exactly once
        assert ToolRegistry.list_tools().count("hot_tool_a") == 1

    def test_needs_reload_false_when_unchanged(self, tmp_path):
        f = tmp_path / "tool_a.py"
        self._write_tool(f, "hot_tool_a")
        loader = CustomToolLoader(tools_dir=tmp_path)
        loader.load_all()
        assert loader.needs_reload() is False

    def test_needs_reload_true_after_touch(self, tmp_path):
        import time

        f = tmp_path / "tool_a.py"
        self._write_tool(f, "hot_tool_a")
        loader = CustomToolLoader(tools_dir=tmp_path)
        loader.load_all()
        time.sleep(0.01)
        f.touch()
        assert loader.needs_reload() is True

    def test_get_tools_returns_loaded_names(self, tmp_path):
        self._write_tool(tmp_path / "tool_a.py", "hot_tool_a")
        loader = CustomToolLoader(tools_dir=tmp_path)
        loader.load_all()
        assert "hot_tool_a" in loader.get_tools()
