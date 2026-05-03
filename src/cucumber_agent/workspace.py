"""Workspace intelligence — auto-detect project type from directory."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

# Per-project-type guidance injected into the system prompt.
_AGENT_CONTEXT: dict[str, str] = {
    "Python": (
        "Dies ist ein Python-Projekt. "
        "Nutze `uv run python` statt globalem `python`, "
        "`uv run pytest` für Tests und `uv run ruff check` für Linting."
    ),
    "Node.js": (
        "Dies ist ein Node.js-Projekt. "
        "Nutze `npm install` / `yarn install` zum Installieren, "
        "`npm test` für Tests und `npm run build` zum Bauen."
    ),
    "Rust": (
        "Dies ist ein Rust-Projekt. "
        "Nutze `cargo build` zum Kompilieren, `cargo test` für Tests "
        "und `cargo clippy` für Linting."
    ),
    "Go": (
        "Dies ist ein Go-Projekt. "
        "Nutze `go build ./...` zum Kompilieren, `go test ./...` für Tests "
        "und `go vet ./...` für statische Analyse."
    ),
    "Java/Maven": (
        "Dies ist ein Java/Maven-Projekt. "
        "Nutze `mvn compile` zum Kompilieren, `mvn test` für Tests "
        "und `mvn package` zum Bauen des Artefakts."
    ),
    "Java/Gradle": (
        "Dies ist ein Java/Gradle-Projekt. "
        "Nutze `./gradlew build` zum Bauen und `./gradlew test` für Tests."
    ),
    "Ruby": (
        "Dies ist ein Ruby-Projekt. "
        "Nutze `bundle install` zum Installieren und `bundle exec rspec` für Tests."
    ),
    "PHP": (
        "Dies ist ein PHP-Projekt. "
        "Nutze `composer install` zum Installieren und `./vendor/bin/phpunit` für Tests."
    ),
    ".NET": (
        "Dies ist ein .NET-Projekt. "
        "Nutze `dotnet build` zum Kompilieren und `dotnet test` für Tests."
    ),
    "C/C++": ("Dies ist ein C/C++-Projekt. Nutze `cmake --build .` oder `make` zum Kompilieren."),
}


@dataclass
class WorkspaceInfo:
    """Detected workspace information."""

    path: Path
    project_type: str | None = None
    package_manager: str | None = None
    git_branch: str | None = None
    venv: Path | None = None
    agent_context: str | None = None

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

    def to_full_context(self) -> str:
        """Extended context string including agent guidance."""
        base = self.to_context_string()
        if self.agent_context:
            return f"{base}\n{self.agent_context}"
        return base


# Ordered list of (filename, project_type, package_manager).
# Glob patterns are supported via ``_glob_match`` below.
_INDICATORS: list[tuple[str, str, str | None]] = [
    ("pyproject.toml", "Python", "uv/pip"),
    ("setup.py", "Python", "pip"),
    ("requirements.txt", "Python", "pip"),
    ("package.json", "Node.js", "npm/yarn"),
    ("Cargo.toml", "Rust", "cargo"),
    ("go.mod", "Go", "go"),
    ("Gemfile", "Ruby", "bundler"),
    ("pom.xml", "Java/Maven", "maven"),
    ("build.gradle", "Java/Gradle", "gradle"),
    ("build.gradle.kts", "Java/Gradle", "gradle"),
    ("CMakeLists.txt", "C/C++", "cmake"),
    ("Makefile", "C/C++", "make"),
    ("composer.json", "PHP", "composer"),
    # .NET: matched via glob *.csproj — handled specially in detect()
]

# Virtual environment directory names to probe (in priority order)
_VENV_NAMES = [".venv", "venv", "env"]


def _detect_package_manager(path: Path, base_pm: str | None) -> str | None:
    """Refine package manager detection (e.g. distinguish uv vs pip)."""
    if base_pm and "uv" in base_pm:
        if (path / "uv.lock").exists():
            return "uv"
        if (path / "poetry.lock").exists():
            return "poetry"
    if base_pm and "npm/yarn" in base_pm:
        if (path / "pnpm-lock.yaml").exists():
            return "pnpm"
        if (path / "yarn.lock").exists():
            return "yarn"
        if (path / "package-lock.json").exists():
            return "npm"
    return base_pm


def detect_git_branch(path: Path | None = None) -> str | None:
    """Return the current git branch name, or None if not a git repo.

    Walks up the directory tree searching for a ``.git`` directory so that
    this function works even when called from a subdirectory of the repo root.
    """
    cwd = path or Path.cwd()
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=2,
        )
        branch = result.stdout.strip()
        return branch if result.returncode == 0 and branch else None
    except Exception:
        return None


# Keep the private alias for backwards compatibility inside this module.
_git_branch = detect_git_branch


def detect_venv(path: Path | None = None) -> Path | None:
    """Search for a Python virtual environment in *path* (defaults to cwd).

    Probes ``.venv``, ``venv``, and ``env`` subdirectories.  Returns the first
    ``Path`` that exists and contains a ``pyvenv.cfg`` file, or ``None``.
    """
    cwd = path or Path.cwd()
    for name in _VENV_NAMES:
        candidate = cwd / name
        if candidate.is_dir() and (candidate / "pyvenv.cfg").exists():
            return candidate
    return None


def _detect_dotnet(path: Path) -> bool:
    """Return True if *path* contains at least one ``.csproj`` file."""
    return any(path.glob("*.csproj"))


class WorkspaceDetector:
    """Detects project type and git status of a directory."""

    @staticmethod
    def detect(path: Path | None = None) -> WorkspaceInfo:
        """Scan `path` (defaults to cwd) and return a WorkspaceInfo."""
        cwd = path or Path.cwd()

        project_type: str | None = None
        package_manager: str | None = None

        # Check static filename indicators
        for filename, ptype, pm in _INDICATORS:
            if (cwd / filename).exists():
                project_type = ptype
                package_manager = _detect_package_manager(cwd, pm)
                break

        # .NET: glob-based detection (*.csproj)
        if project_type is None and _detect_dotnet(cwd):
            project_type = ".NET"
            package_manager = "dotnet"

        branch = detect_git_branch(cwd)
        venv = detect_venv(cwd)
        agent_context = _AGENT_CONTEXT.get(project_type) if project_type else None

        return WorkspaceInfo(
            path=cwd,
            project_type=project_type,
            package_manager=package_manager,
            git_branch=branch,
            venv=venv,
            agent_context=agent_context,
        )
