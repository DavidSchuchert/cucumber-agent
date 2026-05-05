"""Tests for installer and setup wizard safety."""

from __future__ import annotations

import subprocess
import sys
from importlib import util
from pathlib import Path

from cucumber_agent.provider import ProviderRegistry
from cucumber_agent.providers import deepseek, minimax, ollama, openrouter  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


def _load_installer_init():
    spec = util.spec_from_file_location("installer_init", ROOT / "installer" / "init.py")
    assert spec is not None
    assert spec.loader is not None
    module = util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


installer_init = _load_installer_init()


def test_installer_shell_scripts_are_valid_sh():
    """Installer scripts should keep working with the documented `curl | sh` path."""
    for script in ("install.sh", "update.sh", "uninstall.sh"):
        result = subprocess.run(
            ["sh", "-n", str(ROOT / "installer" / script)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr


def test_updater_does_not_hard_reset_user_changes():
    """The updater must not destroy local edits in the installation checkout."""
    update_script = (ROOT / "installer" / "update.sh").read_text(encoding="utf-8")

    assert "reset --hard" not in update_script
    assert "git merge --ff-only origin/main" in update_script
    assert "Local changes detected" in update_script


def test_setup_wizard_only_lists_registered_providers():
    """Every provider offered by the wizard must be available at runtime."""
    registered = set(ProviderRegistry.list_providers())
    offered = {provider for provider, _display, _base_url in installer_init.PROVIDERS.values()}

    assert offered <= registered
    assert {"minimax", "openrouter", "deepseek", "ollama"} <= offered
    assert "nvidia_nim" not in offered
    assert "lmstudio" not in offered


def test_local_provider_does_not_prompt_for_api_key(monkeypatch):
    """Ollama setup should not ask for an API key."""
    asked = False

    def fail_prompt(*args, **kwargs):
        nonlocal asked
        asked = True
        raise AssertionError("Prompt.ask should not be called for Ollama API keys")

    monkeypatch.setattr(installer_init.Prompt, "ask", fail_prompt)

    assert installer_init.get_api_key("ollama", "Ollama") is None
    assert asked is False
