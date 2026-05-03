"""Skill loader — reads ~/.cucumber/skills/*.yaml manifest files."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class Skill:
    """A single loaded skill."""

    name: str
    command: str  # e.g. "/wetter"
    description: str
    prompt: str  # May contain {args} placeholder
    args_hint: str = ""  # e.g. "[Stadt]" shown in /skills list

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
                skill = Skill(
                    name=data.get("name", yaml_file.stem),
                    command=data.get("command", f"/{yaml_file.stem}"),
                    description=data.get("description", ""),
                    prompt=data.get("prompt", ""),
                    args_hint=data.get("args_hint", ""),
                )
                self._skills[yaml_file.stem] = skill
                self._mtimes[yaml_file] = mtime
            except Exception:
                pass  # silently skip malformed skills

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
        for yaml_file in self._dir.glob("*.yaml"):
            if self._mtimes.get(yaml_file) != yaml_file.stat().st_mtime:
                return True
        return False
