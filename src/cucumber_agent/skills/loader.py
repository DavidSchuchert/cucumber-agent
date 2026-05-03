"""Skill loader — reads ~/.cucumber/skills/*.yaml manifest files."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# Required fields for a valid skill YAML
_REQUIRED_FIELDS = ("name", "command", "description", "steps")


@dataclass
class Skill:
    """A single loaded skill."""

    name: str
    command: str  # e.g. "/wetter"
    description: str
    steps: list[str]  # Ordered list of steps the skill performs
    prompt: str = ""  # May contain {args} placeholder
    args_hint: str = ""  # e.g. "[Stadt]" shown in /skills list
    timeout: float = 30.0  # Per-step timeout in seconds

    @property
    def command_key(self) -> str:
        """Normalized command without leading slash."""
        return self.command.lstrip("/")


class SkillLoader:
    """Scans a directory for *.yaml skill manifests."""

    def __init__(self, skills_dir: Path | None = None) -> None:
        self._dir = skills_dir or (Path.home() / ".cucumber" / "skills")
        self._skills: dict[str, Skill] = {}
        self._last_scan: float = 0.0
        self._mtimes: dict[Path, float] = {}

    @property
    def skills(self) -> list[Skill]:
        return list(self._skills.values())

    def _validate(self, data: dict, yaml_file: Path) -> list[str]:
        """Return list of missing required fields (empty = valid)."""
        return [f for f in _REQUIRED_FIELDS if not data.get(f)]

    def load_all(self) -> list[Skill]:
        """Load (or reload if changed) all skills from the skills directory."""
        self._dir.mkdir(parents=True, exist_ok=True)

        current_files = set(self._dir.glob("*.yaml")) | set(self._dir.glob("*.yml"))
        removed = set(self._mtimes.keys()) - current_files

        # Remove skills for deleted files
        for f in removed:
            skill_key = f.stem
            self._skills.pop(skill_key, None)
            del self._mtimes[f]

        # Load/reload changed files
        for yaml_file in sorted(current_files):
            mtime = yaml_file.stat().st_mtime
            if self._mtimes.get(yaml_file) == mtime:
                continue  # unchanged
            try:
                data = yaml.safe_load(yaml_file.read_text(encoding="utf-8")) or {}

                # Schema validation
                missing = self._validate(data, yaml_file)
                if missing:
                    logger.warning(
                        "Skill %s skipped — missing required fields: %s",
                        yaml_file.name,
                        ", ".join(missing),
                    )
                    self._mtimes[yaml_file] = mtime  # mark so we don't warn repeatedly
                    continue

                steps = data["steps"]
                if not isinstance(steps, list):
                    steps = [str(steps)]

                skill = Skill(
                    name=data["name"],
                    command=data["command"],
                    description=data["description"],
                    steps=[str(s) for s in steps],
                    prompt=data.get("prompt", ""),
                    args_hint=data.get("args_hint", ""),
                    timeout=float(data.get("timeout", 30.0)),
                )
                self._skills[yaml_file.stem] = skill
                self._mtimes[yaml_file] = mtime
            except Exception as exc:
                logger.warning("Skill %s could not be loaded: %s", yaml_file.name, exc)

        self._last_scan = time.monotonic()
        return self.skills

    def get(self, command: str) -> Skill | None:
        """Look up a skill by its /command string."""
        cmd = command.lstrip("/").lower()
        for skill in self._skills.values():
            if skill.command_key.lower() == cmd:
                return skill
        return None

    def needs_reload(self) -> bool:
        """True if any skill file has changed since last load (mtime check)."""
        if not self._dir.exists():
            return False
        for pattern in ("*.yaml", "*.yml"):
            for yaml_file in self._dir.glob(pattern):
                if self._mtimes.get(yaml_file) != yaml_file.stat().st_mtime:
                    return True
        return False

    def get_all_descriptions(self) -> str:
        """Return a formatted string of all loaded skills for system-prompt injection.

        Example output::

            Available skills:
            - /git_commit [msg]: Helps craft a good Git commit message.
            - /code_review [path]: Runs a structured code-review workflow.
        """
        if not self._skills:
            return ""

        lines = ["Available skills:"]
        for skill in sorted(self._skills.values(), key=lambda s: s.command_key):
            hint = f" {skill.args_hint}" if skill.args_hint else ""
            lines.append(f"  - /{skill.command_key}{hint}: {skill.description}")
        return "\n".join(lines)
