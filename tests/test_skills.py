"""Tests for the skills system — loader validation, hot-reload, runner utilities."""

from __future__ import annotations

from pathlib import Path

from cucumber_agent.skills.loader import SkillLoader
from cucumber_agent.skills.runner import SkillRunner

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def write_skill(tmp_path: Path, filename: str, content: str) -> Path:
    f = tmp_path / filename
    f.write_text(content, encoding="utf-8")
    return f


VALID_YAML = """\
name: Test Skill
command: /test
description: A test skill
steps:
  - Step one
  - Step two
prompt: "Do {args}"
args_hint: "[value]"
timeout: 15
"""

MISSING_STEPS_YAML = """\
name: Bad Skill
command: /bad
description: Missing steps field
"""

MISSING_NAME_YAML = """\
command: /noname
description: Missing name
steps:
  - Do something
"""

MISSING_MULTIPLE_YAML = """\
description: Only description present
"""


# ---------------------------------------------------------------------------
# A. loader.py — schema validation
# ---------------------------------------------------------------------------


class TestSkillLoaderValidation:
    def test_valid_skill_is_loaded(self, tmp_path):
        """A fully valid YAML is loaded without warnings."""
        write_skill(tmp_path, "valid.yaml", VALID_YAML)
        loader = SkillLoader(skills_dir=tmp_path)
        skills = loader.load_all()

        assert len(skills) == 1
        s = skills[0]
        assert s.name == "Test Skill"
        assert s.command == "/test"
        assert s.steps == ["Step one", "Step two"]
        assert s.timeout == 15.0
        assert s.args_hint == "[value]"

    def test_missing_steps_skips_skill(self, tmp_path, caplog):
        """A YAML missing 'steps' is skipped with a warning."""
        import logging

        write_skill(tmp_path, "bad.yaml", MISSING_STEPS_YAML)
        loader = SkillLoader(skills_dir=tmp_path)

        with caplog.at_level(logging.WARNING, logger="cucumber_agent.skills.loader"):
            skills = loader.load_all()

        assert len(skills) == 0
        assert any("steps" in msg for msg in caplog.messages)

    def test_missing_name_skips_skill(self, tmp_path, caplog):
        """A YAML missing 'name' is skipped with a warning."""
        import logging

        write_skill(tmp_path, "noname.yaml", MISSING_NAME_YAML)
        loader = SkillLoader(skills_dir=tmp_path)

        with caplog.at_level(logging.WARNING, logger="cucumber_agent.skills.loader"):
            skills = loader.load_all()

        assert len(skills) == 0
        assert any("name" in msg for msg in caplog.messages)

    def test_multiple_missing_fields_reports_all(self, tmp_path, caplog):
        """All missing required fields are mentioned in the warning."""
        import logging

        write_skill(tmp_path, "multi.yaml", MISSING_MULTIPLE_YAML)
        loader = SkillLoader(skills_dir=tmp_path)

        with caplog.at_level(logging.WARNING, logger="cucumber_agent.skills.loader"):
            loader.load_all()

        # Should mention name, command, steps at minimum
        combined = " ".join(caplog.messages)
        assert "name" in combined
        assert "command" in combined
        assert "steps" in combined

    def test_valid_and_invalid_mixed(self, tmp_path):
        """Only valid skills are loaded when mixed with invalid ones."""
        write_skill(tmp_path, "valid.yaml", VALID_YAML)
        write_skill(tmp_path, "bad.yaml", MISSING_STEPS_YAML)
        loader = SkillLoader(skills_dir=tmp_path)
        skills = loader.load_all()

        assert len(skills) == 1
        assert skills[0].name == "Test Skill"


# ---------------------------------------------------------------------------
# B. loader.py — get_all_descriptions()
# ---------------------------------------------------------------------------


class TestGetAllDescriptions:
    def test_empty_loader_returns_empty_string(self, tmp_path):
        loader = SkillLoader(skills_dir=tmp_path)
        loader.load_all()
        assert loader.get_all_descriptions() == ""

    def test_descriptions_contain_command_and_description(self, tmp_path):
        write_skill(tmp_path, "valid.yaml", VALID_YAML)
        loader = SkillLoader(skills_dir=tmp_path)
        loader.load_all()

        desc = loader.get_all_descriptions()
        assert "/test" in desc
        assert "A test skill" in desc
        assert "Available skills:" in desc

    def test_descriptions_include_args_hint(self, tmp_path):
        write_skill(tmp_path, "valid.yaml", VALID_YAML)
        loader = SkillLoader(skills_dir=tmp_path)
        loader.load_all()

        desc = loader.get_all_descriptions()
        assert "[value]" in desc

    def test_multiple_skills_all_listed(self, tmp_path):
        second = VALID_YAML.replace("Test Skill", "Second Skill").replace("/test", "/second")
        write_skill(tmp_path, "valid.yaml", VALID_YAML)
        write_skill(tmp_path, "second.yaml", second)
        loader = SkillLoader(skills_dir=tmp_path)
        loader.load_all()

        desc = loader.get_all_descriptions()
        assert "/test" in desc
        assert "/second" in desc


# ---------------------------------------------------------------------------
# C. loader.py — hot-reload
# ---------------------------------------------------------------------------


class TestHotReload:
    def test_needs_reload_detects_new_file(self, tmp_path):
        loader = SkillLoader(skills_dir=tmp_path)
        loader.load_all()
        assert loader.needs_reload() is False

        write_skill(tmp_path, "new.yaml", VALID_YAML)
        assert loader.needs_reload() is True

    def test_removed_skill_disappears_on_reload(self, tmp_path):
        p = write_skill(tmp_path, "valid.yaml", VALID_YAML)
        loader = SkillLoader(skills_dir=tmp_path)
        loader.load_all()
        assert len(loader.skills) == 1

        p.unlink()
        loader.load_all()
        assert len(loader.skills) == 0

    def test_get_by_command_key(self, tmp_path):
        write_skill(tmp_path, "valid.yaml", VALID_YAML)
        loader = SkillLoader(skills_dir=tmp_path)
        loader.load_all()

        skill = loader.get("/test")
        assert skill is not None
        assert skill.name == "Test Skill"

        assert loader.get("/nonexistent") is None


# ---------------------------------------------------------------------------
# D. runner.py — list_skills() and _clean_response()
# ---------------------------------------------------------------------------


class TestSkillRunner:
    def test_list_skills_returns_dicts(self, tmp_path):
        write_skill(tmp_path, "valid.yaml", VALID_YAML)
        loader = SkillLoader(skills_dir=tmp_path)
        loader.load_all()

        result = SkillRunner.list_skills(loader)

        assert isinstance(result, list)
        assert len(result) == 1
        item = result[0]
        assert item["name"] == "Test Skill"
        assert item["command"] == "/test"
        assert item["description"] == "A test skill"
        assert item["steps"] == ["Step one", "Step two"]
        assert item["timeout"] == 15.0

    def test_list_skills_empty_loader(self, tmp_path):
        loader = SkillLoader(skills_dir=tmp_path)
        loader.load_all()
        assert SkillRunner.list_skills(loader) == []

    def test_clean_response_removes_thinking_blocks(self):
        raw = "<thinking>Let me reason...</thinking>\nThe answer is 42."
        cleaned = SkillRunner._clean_response(raw)
        assert "<thinking>" not in cleaned
        assert "The answer is 42." in cleaned

    def test_clean_response_removes_i_will_preambles(self):
        raw = "I will now analyze the code.\n\nHere are the results."
        cleaned = SkillRunner._clean_response(raw)
        assert "I will" not in cleaned
        assert "Here are the results." in cleaned

    def test_clean_response_preserves_normal_text(self):
        raw = "The function `foo()` returns None.\nSee line 42."
        cleaned = SkillRunner._clean_response(raw)
        assert cleaned == raw

    def test_list_skills_contains_all_required_keys(self, tmp_path):
        write_skill(tmp_path, "valid.yaml", VALID_YAML)
        loader = SkillLoader(skills_dir=tmp_path)
        loader.load_all()

        required_keys = {"name", "command", "description", "args_hint", "steps", "timeout"}
        for item in SkillRunner.list_skills(loader):
            assert required_keys <= item.keys()


# ---------------------------------------------------------------------------
# E. Skill dataclass — timeout default
# ---------------------------------------------------------------------------


class TestSkillDataclass:
    def test_default_timeout_is_30(self, tmp_path):
        yaml_no_timeout = """\
name: No Timeout
command: /notimeout
description: No timeout specified
steps:
  - Do it
"""
        write_skill(tmp_path, "notimeout.yaml", yaml_no_timeout)
        loader = SkillLoader(skills_dir=tmp_path)
        skills = loader.load_all()

        assert skills[0].timeout == 30.0

    def test_custom_timeout_is_respected(self, tmp_path):
        write_skill(tmp_path, "valid.yaml", VALID_YAML)
        loader = SkillLoader(skills_dir=tmp_path)
        skills = loader.load_all()

        assert skills[0].timeout == 15.0

    def test_steps_always_list_of_strings(self, tmp_path):
        yaml_scalar_step = """\
name: Scalar Step
command: /scalar
description: Steps as scalar (edge case)
steps: Just one step as a string
"""
        write_skill(tmp_path, "scalar.yaml", yaml_scalar_step)
        loader = SkillLoader(skills_dir=tmp_path)
        skills = loader.load_all()

        assert isinstance(skills[0].steps, list)
        assert all(isinstance(s, str) for s in skills[0].steps)
