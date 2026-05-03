"""Tests for workspace detection and smart-retry improvements."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cucumber_agent.smart_retry import (
    CommandCategory,
    classify_command,
    suggest_path_alternatives,
)
from cucumber_agent.workspace import (
    WorkspaceDetector,
    WorkspaceInfo,
    detect_git_branch,
    detect_venv,
)

# ---------------------------------------------------------------------------
# WorkspaceDetector — project-type detection
# ---------------------------------------------------------------------------


def test_detect_python_project(tmp_path: Path) -> None:
    """pyproject.toml triggers Python detection."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    info = WorkspaceDetector.detect(tmp_path)
    assert info.project_type == "Python"
    assert info.package_manager in ("uv", "uv/pip", "poetry", "pip")


def test_detect_rust_project(tmp_path: Path) -> None:
    """Cargo.toml triggers Rust detection with cargo package manager."""
    (tmp_path / "Cargo.toml").write_text('[package]\nname = "myapp"\nversion = "0.1.0"\n')
    info = WorkspaceDetector.detect(tmp_path)
    assert info.project_type == "Rust"
    assert info.package_manager == "cargo"


def test_detect_go_project(tmp_path: Path) -> None:
    """go.mod triggers Go detection."""
    (tmp_path / "go.mod").write_text("module example.com/myapp\n\ngo 1.21\n")
    info = WorkspaceDetector.detect(tmp_path)
    assert info.project_type == "Go"
    assert info.package_manager == "go"


def test_detect_java_maven_project(tmp_path: Path) -> None:
    """pom.xml triggers Java/Maven detection."""
    (tmp_path / "pom.xml").write_text(
        "<project><groupId>com.example</groupId></project>\n"
    )
    info = WorkspaceDetector.detect(tmp_path)
    assert info.project_type == "Java/Maven"
    assert info.package_manager == "maven"


def test_detect_java_gradle_project(tmp_path: Path) -> None:
    """build.gradle triggers Java/Gradle detection."""
    (tmp_path / "build.gradle").write_text("plugins { id 'java' }\n")
    info = WorkspaceDetector.detect(tmp_path)
    assert info.project_type == "Java/Gradle"
    assert info.package_manager == "gradle"


def test_detect_php_project(tmp_path: Path) -> None:
    """composer.json triggers PHP detection."""
    (tmp_path / "composer.json").write_text('{"require": {}}\n')
    info = WorkspaceDetector.detect(tmp_path)
    assert info.project_type == "PHP"
    assert info.package_manager == "composer"


def test_detect_dotnet_project(tmp_path: Path) -> None:
    """.csproj file triggers .NET detection."""
    (tmp_path / "MyApp.csproj").write_text(
        "<Project Sdk=\"Microsoft.NET.Sdk\"></Project>\n"
    )
    info = WorkspaceDetector.detect(tmp_path)
    assert info.project_type == ".NET"
    assert info.package_manager == "dotnet"


def test_detect_node_project(tmp_path: Path) -> None:
    """package.json triggers Node.js detection."""
    (tmp_path / "package.json").write_text('{"name": "myapp", "version": "1.0.0"}\n')
    info = WorkspaceDetector.detect(tmp_path)
    assert info.project_type == "Node.js"


def test_detect_node_yarn_project(tmp_path: Path) -> None:
    """yarn.lock refines package manager to yarn."""
    (tmp_path / "package.json").write_text('{"name": "myapp"}\n')
    (tmp_path / "yarn.lock").write_text("# yarn lockfile v1\n")
    info = WorkspaceDetector.detect(tmp_path)
    assert info.project_type == "Node.js"
    assert info.package_manager == "yarn"


def test_detect_unknown_project(tmp_path: Path) -> None:
    """Empty directory yields no project_type."""
    info = WorkspaceDetector.detect(tmp_path)
    assert info.project_type is None
    assert info.package_manager is None


def test_agent_context_rust(tmp_path: Path) -> None:
    """Rust projects get cargo-specific agent context."""
    (tmp_path / "Cargo.toml").write_text('[package]\nname = "x"\nversion = "0.1.0"\n')
    info = WorkspaceDetector.detect(tmp_path)
    assert info.agent_context is not None
    assert "cargo" in info.agent_context.lower()


def test_agent_context_go(tmp_path: Path) -> None:
    """Go projects get go-specific agent context."""
    (tmp_path / "go.mod").write_text("module example.com/x\n\ngo 1.21\n")
    info = WorkspaceDetector.detect(tmp_path)
    assert info.agent_context is not None
    assert "go" in info.agent_context.lower()


def test_to_full_context_includes_guidance(tmp_path: Path) -> None:
    """to_full_context() appends agent_context below the workspace line."""
    (tmp_path / "Cargo.toml").write_text('[package]\nname = "x"\nversion = "0.1.0"\n')
    info = WorkspaceDetector.detect(tmp_path)
    full = info.to_full_context()
    assert "Workspace:" in full
    assert "cargo" in full.lower()


# ---------------------------------------------------------------------------
# detect_venv
# ---------------------------------------------------------------------------


def test_detect_venv_finds_dotenv(tmp_path: Path) -> None:
    """.venv with pyvenv.cfg is detected."""
    venv_dir = tmp_path / ".venv"
    venv_dir.mkdir()
    (venv_dir / "pyvenv.cfg").write_text("home = /usr/bin\n")
    result = detect_venv(tmp_path)
    assert result == venv_dir


def test_detect_venv_finds_plain_venv(tmp_path: Path) -> None:
    """Plain venv/ directory is detected when .venv is absent."""
    venv_dir = tmp_path / "venv"
    venv_dir.mkdir()
    (venv_dir / "pyvenv.cfg").write_text("home = /usr/bin\n")
    result = detect_venv(tmp_path)
    assert result == venv_dir


def test_detect_venv_missing(tmp_path: Path) -> None:
    """Returns None when no venv is present."""
    assert detect_venv(tmp_path) is None


def test_detect_venv_dir_without_cfg(tmp_path: Path) -> None:
    """.venv directory without pyvenv.cfg is not treated as a venv."""
    venv_dir = tmp_path / ".venv"
    venv_dir.mkdir()
    # No pyvenv.cfg
    assert detect_venv(tmp_path) is None


# ---------------------------------------------------------------------------
# detect_git_branch
# ---------------------------------------------------------------------------


def test_detect_git_branch_returns_string_or_none(tmp_path: Path) -> None:
    """Returns a string in an actual git repo or None elsewhere."""
    # tmp_path is not a git repo — should return None
    result = detect_git_branch(tmp_path)
    assert result is None or isinstance(result, str)


def test_detect_git_branch_in_repo() -> None:
    """Returns a non-empty string when called inside a real git repo."""
    import subprocess

    repo = Path(
        subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
        ).strip()
    )
    branch = detect_git_branch(repo)
    assert isinstance(branch, str) and len(branch) > 0


# ---------------------------------------------------------------------------
# WorkspaceInfo helpers
# ---------------------------------------------------------------------------


def test_to_context_string_format(tmp_path: Path) -> None:
    """to_context_string() contains project type, package manager and path."""
    info = WorkspaceInfo(
        path=tmp_path,
        project_type="Rust",
        package_manager="cargo",
        git_branch="main",
    )
    ctx = info.to_context_string()
    assert "Workspace:" in ctx
    assert "Rust" in ctx
    assert "cargo" in ctx
    assert "main" in ctx


def test_to_context_string_no_branch(tmp_path: Path) -> None:
    """to_context_string() works when git_branch is None."""
    info = WorkspaceInfo(path=tmp_path, project_type="Go", package_manager="go")
    ctx = info.to_context_string()
    assert "Go" in ctx
    assert "git:" not in ctx


# ---------------------------------------------------------------------------
# classify_command — edge cases and shell-specific syntax
# ---------------------------------------------------------------------------


def test_classify_read_ls() -> None:
    assert classify_command("ls -la ~/Documents") == CommandCategory.READ


def test_classify_read_git_log() -> None:
    assert classify_command("git log --oneline -n 5") == CommandCategory.READ


def test_classify_destructive_rm() -> None:
    assert classify_command("rm -rf /tmp/foo") == CommandCategory.DESTRUCTIVE


def test_classify_destructive_mv() -> None:
    assert classify_command("mv old.txt new.txt") == CommandCategory.DESTRUCTIVE


def test_classify_write_mkdir() -> None:
    assert classify_command("mkdir -p /tmp/mydir") == CommandCategory.WRITE


def test_classify_write_curl_download() -> None:
    assert classify_command("curl https://example.com -o file.zip") == CommandCategory.WRITE


def test_classify_read_pwd() -> None:
    """pwd is a read-only operation (zsh/fish support)."""
    assert classify_command("pwd") == CommandCategory.READ


def test_classify_read_printenv() -> None:
    """printenv is read-only (fish/zsh)."""
    assert classify_command("printenv PATH") == CommandCategory.READ


def test_classify_write_export() -> None:
    """export modifies shell environment — treat as write."""
    assert classify_command("export FOO=bar") == CommandCategory.WRITE


def test_classify_write_source() -> None:
    """source modifies shell state — treat as write."""
    assert classify_command("source ~/.zshrc") == CommandCategory.WRITE


def test_classify_write_unset() -> None:
    """unset modifies environment — treat as write."""
    assert classify_command("unset MY_VAR") == CommandCategory.WRITE


def test_classify_unknown() -> None:
    """Completely unknown command returns UNKNOWN."""
    assert classify_command("xyzzy-unknown-cmd --flag") == CommandCategory.UNKNOWN


# ---------------------------------------------------------------------------
# PATH_MAPPINGS — new German↔English pairs
# ---------------------------------------------------------------------------


def test_path_mapping_desktop_german() -> None:
    """Schreibtisch → Desktop alternative is suggested."""
    alts = suggest_path_alternatives("ls ~/Schreibtisch/notes")
    assert any("desktop" in a.lower() for a in alts)


def test_path_mapping_movies_german() -> None:
    """Filme → Movies alternative is suggested."""
    alts = suggest_path_alternatives("ls ~/Filme")
    assert any("movies" in a.lower() for a in alts)


def test_path_mapping_movies_english() -> None:
    """Movies → Filme alternative is suggested."""
    alts = suggest_path_alternatives("ls ~/Movies")
    assert any("filme" in a.lower() for a in alts)


def test_path_mapping_public_german() -> None:
    """Öffentlich → Public alternative is suggested."""
    alts = suggest_path_alternatives("ls ~/Öffentlich")
    assert any("public" in a.lower() for a in alts)


def test_path_mapping_music_english() -> None:
    """Music → Musik alternative is suggested."""
    alts = suggest_path_alternatives("open ~/Music/playlist.m3u")
    assert any("musik" in a.lower() for a in alts)
