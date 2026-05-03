"""Shared pytest fixtures for cucumber-agent tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from cucumber_agent.config import AgentConfig, Config, ContextConfig, MemoryConfig, PersonalityConfig
from cucumber_agent.session import Session


def make_personality_file(tmp_path: Path, content: str | None = None) -> Path:
    pers_dir = tmp_path / "personality"
    pers_dir.mkdir(parents=True, exist_ok=True)
    pers_file = pers_dir / "personality.md"
    pers_file.write_text(
        content or "# Personality\nname: TestBot\nemoji: 🤖\ntone: friendly\nlanguage: en\n",
        encoding="utf-8",
    )
    return pers_file


def make_config(tmp_path: Path, personality_content: str | None = None) -> Config:
    pers_file = make_personality_file(tmp_path, personality_content)
    cfg = Config(config_dir=tmp_path)
    cfg.personality = PersonalityConfig.from_markdown(pers_file)
    cfg.agent = AgentConfig(
        provider="openrouter",
        model="openai/gpt-4o-mini",
        system_prompt=cfg.personality.to_system_prompt(),
    )
    cfg.context = ContextConfig(max_tokens=8000, remember_last=6)
    cfg.memory = MemoryConfig(
        enabled=True,
        log_dir=tmp_path / "memory",
        facts_file=tmp_path / "memory" / "facts.json",
        summary_file=tmp_path / "memory" / "last_summary.txt",
        max_session_messages=20,
        summarize_keep_recent=6,
    )
    return cfg


def make_session(config: Config) -> Session:
    return Session(id="test", model=config.agent.model)


def make_mock_provider(response_content: str = "test response") -> MagicMock:
    provider = MagicMock()
    provider.complete = AsyncMock(
        return_value=MagicMock(
            content=response_content,
            tool_calls=None,
            input_tokens=10,
            output_tokens=5,
            model="openai/gpt-4o-mini",
        )
    )
    provider.stream = AsyncMock()
    return provider
