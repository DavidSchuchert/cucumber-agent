"""Workspace intelligence — auto-detect project type from directory."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class WorkspaceInfo:
    """Detected workspace information."""

    path: Path
    project_type: str | None = None
    package_manager: str | None = None
    git_branch: str | None = None

    def to_context_string(self) -> str:
        """Compact single-line string for system prompt injection (~15 tokens)."""
        parts = []
        if self.project_type:
            parts.append(self.project_type)
        if self.package_manager:
            parts.append(f"[{self.package_manager}]")
        location = f"@ {self.path}"
        if self.git_branch:
            location += f" (git: {self.git_branch})"
        parts.append(location)
        return "Workspace: " + " ".join(parts)


# Ordered list of (filename, project_type, package_manager)
_INDICATORS: list[tuple[str, str, str | None]] = [
    ("pyproject.toml", "Python",     "uv/pip"),
    ("setup.py",       "Python",     "pip"),
    ("requirements.txt","Python",    "pip"),
    ("package.json",   "Node.js",    "npm/yarn"),
    ("Cargo.toml",     "Rust",       "cargo"),
    ("go.mod",         "Go",         "go"),
    ("Gemfile",        "Ruby",       "bundler"),
    ("pom.xml",        "Java/Maven", "maven"),
    ("build.gradle",   "Java/Gradle","gradle"),
    ("CMakeLists.txt", "C/C++",      "cmake"),
    ("Makefile",       "C/C++",      "make"),
    ("composer.json",  "PHP",        "composer"),
]


def _detect_package_manager(path: Path, base_pm: str | None) -> str | None:
    """Refine package manager detection (e.g. distinguish uv vs pip)."""
    if base_pm and "uv" in base_pm:
        if (path / "uv.lock").exists():
            return "uv"
        if (path / "poetry.lock").exists():
            return "poetry"
    return base_pm


def _git_branch(path: Path) -> str | None:
    """Return current git branch name, or None if not a git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=2,
        )
        branch = result.stdout.strip()
        return branch if result.returncode == 0 and branch else None
    except Exception:
        return None


class WorkspaceDetector:
    """Detects project type and git status of a directory."""

    @staticmethod
    def detect(path: Path | None = None) -> WorkspaceInfo:
        """Scan `path` (defaults to cwd) and return a WorkspaceInfo."""
        cwd = path or Path.cwd()

        project_type: str | None = None
        package_manager: str | None = None

        for filename, ptype, pm in _INDICATORS:
            if (cwd / filename).exists():
                project_type = ptype
                package_manager = _detect_package_manager(cwd, pm)
                break

        # Walk up to find a git repo
        branch = _git_branch(cwd)

        return WorkspaceInfo(
            path=cwd,
            project_type=project_type,
            package_manager=package_manager,
            git_branch=branch,
        )
