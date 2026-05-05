"""Tests for the Config system — env-var overrides, validation, from_env, schema compat."""

from __future__ import annotations

import warnings
from pathlib import Path

import yaml

from cucumber_agent.config import Config, ProviderConfig

# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #


def _write_yaml(path: Path, data: dict) -> Path:
    """Write a YAML file and return its path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(data, f)
    return path


def _make_minimal_config_dir(tmp_path: Path) -> Path:
    """Create a minimal config dir with a config.yaml and personality.md."""
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    (cfg_dir / "personality").mkdir()
    (cfg_dir / "personality" / "personality.md").write_text(
        "# Personality\nname: TestBot\ntone: friendly\nlanguage: en\n"
    )
    _write_yaml(
        cfg_dir / "config.yaml",
        {
            "agent": {"provider": "openrouter", "model": "openai/gpt-4o-mini"},
            "providers": {"openrouter": {"api_key": "test-key"}},
        },
    )
    return cfg_dir


# ------------------------------------------------------------------ #
# A. Env-var overrides in Config.load()
# ------------------------------------------------------------------ #


def test_env_minimax_api_key_applied(tmp_path, monkeypatch):
    """MINIMAX_API_KEY env var should populate providers['minimax'].api_key."""
    monkeypatch.setenv("MINIMAX_API_KEY", "mm-secret")
    cfg_dir = _make_minimal_config_dir(tmp_path)
    cfg = Config.load(config_dir=cfg_dir)
    assert cfg.providers["minimax"].api_key == "mm-secret"


def test_env_openrouter_api_key_overrides_yaml(tmp_path, monkeypatch):
    """OPENROUTER_API_KEY from env should override value in config.yaml."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "env-key")
    cfg_dir = _make_minimal_config_dir(tmp_path)
    cfg = Config.load(config_dir=cfg_dir)
    assert cfg.providers["openrouter"].api_key == "env-key"


def test_env_ollama_base_url(tmp_path, monkeypatch):
    """OLLAMA_BASE_URL env var should populate providers['ollama'].base_url."""
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://my-ollama:11434")
    cfg_dir = _make_minimal_config_dir(tmp_path)
    cfg = Config.load(config_dir=cfg_dir)
    assert cfg.providers["ollama"].base_url == "http://my-ollama:11434"


def test_env_deepseek_api_key(tmp_path, monkeypatch):
    """DEEPSEEK_API_KEY env var should populate providers['deepseek'].api_key."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-abc123")
    cfg_dir = _make_minimal_config_dir(tmp_path)
    cfg = Config.load(config_dir=cfg_dir)
    assert cfg.providers["deepseek"].api_key == "ds-abc123"


def test_env_cucumber_model_overrides(tmp_path, monkeypatch):
    """CUCUMBER_MODEL env var should override agent.model."""
    monkeypatch.setenv("CUCUMBER_MODEL", "anthropic/claude-3-haiku")
    cfg_dir = _make_minimal_config_dir(tmp_path)
    cfg = Config.load(config_dir=cfg_dir)
    assert cfg.agent.model == "anthropic/claude-3-haiku"


def test_env_cucumber_provider_overrides(tmp_path, monkeypatch):
    """CUCUMBER_PROVIDER env var should override agent.provider."""
    monkeypatch.setenv("CUCUMBER_PROVIDER", "deepseek")
    cfg_dir = _make_minimal_config_dir(tmp_path)
    cfg = Config.load(config_dir=cfg_dir)
    assert cfg.agent.provider == "deepseek"


def test_system_prompt_uses_cucumber_install_dir_for_wiki(tmp_path, monkeypatch):
    """Project self-awareness should follow the configured installation directory."""
    install_dir = tmp_path / "install"
    wiki_dir = install_dir / "wiki"
    wiki_dir.mkdir(parents=True)
    (wiki_dir / "README.md").write_text("# Wiki\n", encoding="utf-8")
    monkeypatch.setenv("CUCUMBER_INSTALL_DIR", str(install_dir))

    prompt = Config().personality.to_system_prompt()

    assert f"PROJECT WIKI LOCATION: {install_dir}/wiki/" in prompt
    assert f"- README: {wiki_dir / 'README.md'}" in prompt


# ------------------------------------------------------------------ #
# B. Config.validate()
# ------------------------------------------------------------------ #


def test_validate_passes_with_api_key(tmp_path):
    """validate() returns empty list when provider is configured with an api_key."""
    cfg = Config()
    cfg.providers["openrouter"] = ProviderConfig(name="openrouter", api_key="valid-key")
    cfg.agent.provider = "openrouter"
    cfg.agent.model = "openai/gpt-4o-mini"
    # Use tmp_path for memory so the dir check works
    cfg.memory.log_dir = tmp_path / "memory"
    cfg.memory.log_dir.mkdir()
    issues = cfg.validate()
    assert issues == []


def test_validate_warns_missing_api_key():
    """validate() reports an issue when the active provider has no api_key."""
    cfg = Config()
    cfg.providers["openrouter"] = ProviderConfig(name="openrouter", api_key=None)
    cfg.agent.provider = "openrouter"
    issues = cfg.validate()
    assert any("api_key" in msg or "OPENROUTER_API_KEY" in msg for msg in issues)


def test_validate_warns_missing_provider_entry():
    """validate() reports an issue when the active provider has no config entry at all."""
    cfg = Config()
    cfg.agent.provider = "minimax"
    # No entry in providers dict
    issues = cfg.validate()
    assert any("minimax" in msg for msg in issues)


def test_validate_warns_unusual_model_name():
    """validate() warns when model name doesn't match any known prefix."""
    cfg = Config()
    cfg.providers["openrouter"] = ProviderConfig(name="openrouter", api_key="key")
    cfg.agent.provider = "openrouter"
    cfg.agent.model = "totally-unknown-model-xyz"
    issues = cfg.validate()
    assert any("totally-unknown-model-xyz" in msg for msg in issues)


def test_validate_ollama_needs_base_url():
    """validate() reports issue when ollama is selected but no base_url is configured."""
    cfg = Config()
    cfg.agent.provider = "ollama"
    cfg.providers["ollama"] = ProviderConfig(name="ollama", base_url=None)
    issues = cfg.validate()
    assert any("base_url" in msg or "OLLAMA_BASE_URL" in msg for msg in issues)


def test_validate_memory_dir_not_writable(tmp_path):
    """validate() reports issue when memory dir exists but is not writable."""
    mem_dir = tmp_path / "readonly_memory"
    mem_dir.mkdir()
    mem_dir.chmod(0o444)  # read-only
    cfg = Config()
    cfg.providers["openrouter"] = ProviderConfig(name="openrouter", api_key="key")
    cfg.agent.provider = "openrouter"
    cfg.agent.model = "openai/gpt-4o-mini"
    cfg.memory.log_dir = mem_dir
    try:
        issues = cfg.validate()
        assert any("not writable" in msg for msg in issues)
    finally:
        mem_dir.chmod(0o755)  # restore so pytest can clean up


# ------------------------------------------------------------------ #
# C. Config.from_env()
# ------------------------------------------------------------------ #


def test_from_env_no_yaml_needed(monkeypatch):
    """from_env() returns a Config without requiring any config file."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "env-only-key")
    monkeypatch.setenv("CUCUMBER_MODEL", "openai/gpt-4o")
    cfg = Config.from_env()
    assert cfg.providers["openrouter"].api_key == "env-only-key"
    assert cfg.agent.model == "openai/gpt-4o"


def test_from_env_empty_gives_defaults(monkeypatch):
    """from_env() with no relevant env vars gives a default Config."""
    # Ensure none of our env vars are set
    for var in (
        "MINIMAX_API_KEY",
        "OPENROUTER_API_KEY",
        "DEEPSEEK_API_KEY",
        "OLLAMA_BASE_URL",
        "CUCUMBER_MODEL",
        "CUCUMBER_PROVIDER",
    ):
        monkeypatch.delenv(var, raising=False)
    cfg = Config.from_env()
    assert cfg.agent.provider == "openrouter"
    assert cfg.agent.model == "openai/gpt-4o-mini"
    assert "openrouter" not in cfg.providers  # no entry created without env var


# ------------------------------------------------------------------ #
# D. Unknown YAML keys are silently ignored
# ------------------------------------------------------------------ #


def test_load_ignores_unknown_yaml_keys(tmp_path):
    """Config.load() must not crash when config.yaml has unknown top-level keys."""
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    (cfg_dir / "personality").mkdir()
    (cfg_dir / "personality" / "personality.md").write_text(
        "name: TestBot\ntone: friendly\nlanguage: en\n"
    )
    _write_yaml(
        cfg_dir / "config.yaml",
        {
            "agent": {"provider": "openrouter", "model": "openai/gpt-4o-mini"},
            "providers": {"openrouter": {"api_key": "k"}},
            "totally_unknown_field": "should be ignored",
            "another_future_key": {"nested": True},
        },
    )
    # Should not raise
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cfg = Config.load(config_dir=cfg_dir)
    assert cfg.agent.provider == "openrouter"


def test_load_warns_about_unknown_yaml_keys(tmp_path):
    """Config.load() should emit a UserWarning for unknown YAML keys."""
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    (cfg_dir / "personality").mkdir()
    (cfg_dir / "personality" / "personality.md").write_text("name: TestBot\nlanguage: en\n")
    _write_yaml(
        cfg_dir / "config.yaml",
        {
            "agent": {"provider": "openrouter"},
            "unknown_key_xyz": "surprise",
        },
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        Config.load(config_dir=cfg_dir)
    messages = [str(w.message) for w in caught]
    assert any("unknown_key_xyz" in m for m in messages)


# ------------------------------------------------------------------ #
# E. No config.yaml → defaults still work
# ------------------------------------------------------------------ #


def test_load_no_file_returns_defaults(tmp_path):
    """Config.load() with missing config.yaml returns default values."""
    cfg_dir = tmp_path / "empty_cfg"
    cfg_dir.mkdir()
    cfg = Config.load(config_dir=cfg_dir)
    assert cfg.agent.provider == "openrouter"
    assert cfg.agent.model == "openai/gpt-4o-mini"
