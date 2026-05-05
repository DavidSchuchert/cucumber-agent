"""Tests for personality preservation — identity must survive compression and optimize."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import make_config, make_mock_provider, make_session

from cucumber_agent.agent import Agent
from cucumber_agent.session import Message, Role


def make_agent(tmp_path: Path, personality_content: str | None = None) -> Agent:
    cfg = make_config(tmp_path, personality_content)
    return Agent(provider=make_mock_provider(), config=cfg)


def test_build_messages_contains_core_identity(tmp_path):
    """_build_messages must inject the CORE IDENTITY block in the system message."""
    agent = make_agent(tmp_path)
    session = make_session(agent._config)
    messages = agent._build_messages(session)

    system_msgs = [m for m in messages if m.role == Role.SYSTEM]
    assert system_msgs, "Expected at least one SYSTEM message"
    content = system_msgs[0].content
    assert "=== CORE IDENTITY (IMMUTABLE) ===" in content
    assert "=== END CORE IDENTITY ===" in content


def test_build_messages_contains_memory_identity_contract(tmp_path):
    """_build_messages must inject the immutable memory and identity contract."""
    agent = make_agent(tmp_path)
    session = make_session(agent._config)
    messages = agent._build_messages(session)

    system_msg = next(m for m in messages if m.role == Role.SYSTEM)
    assert "=== MEMORY & IDENTITY CONTRACT ===" in system_msg.content
    assert "Never replace, summarize away, or ignore it" in system_msg.content
    assert "=== END MEMORY & IDENTITY CONTRACT ===" in system_msg.content


def test_validate_identity_preserved_positive(tmp_path):
    agent = make_agent(tmp_path)
    session = make_session(agent._config)
    messages = agent._build_messages(session)
    assert agent._validate_identity_preserved(messages) is True


def test_validate_identity_preserved_negative(tmp_path):
    agent = make_agent(tmp_path)
    plain = [
        Message(role=Role.SYSTEM, content="You are a helpful assistant."),
        Message(role=Role.USER, content="Hello"),
    ]
    assert agent._validate_identity_preserved(plain) is False


def test_validate_identity_requires_memory_contract(tmp_path):
    agent = make_agent(tmp_path)
    incomplete = [
        Message(
            role=Role.SYSTEM,
            content="=== CORE IDENTITY (IMMUTABLE) ===\nname: Test\n=== END CORE IDENTITY ===",
        )
    ]
    assert agent._validate_identity_preserved(incomplete) is False


@pytest.mark.asyncio
async def test_compress_session_excludes_personality(tmp_path):
    """compress_session prompt must explicitly exclude personality content."""
    cfg = make_config(tmp_path)
    provider = make_mock_provider("Benutzer fragte nach dem Wetter.")
    agent = Agent(provider=provider, config=cfg)
    session = make_session(cfg)

    for i in range(12):
        session.messages.append(
            Message(role=Role.USER if i % 2 == 0 else Role.ASSISTANT, content=f"msg {i}")
        )

    await agent.compress_session(session)

    assert provider.complete.called
    call_kwargs = provider.complete.call_args.kwargs
    system_override = call_kwargs.get("system_override", "")
    assert system_override, "compress_session must pass system_override"
    assert any(kw in system_override for kw in ["Persönlichkeit", "NICHT", "unveränderlich"]), (
        f"compress_session must exclude personality. Got: {system_override!r}"
    )


def test_build_messages_reloads_identity_from_disk(tmp_path):
    """_build_messages reloads personality.md on every call — live edits are reflected."""
    agent = make_agent(
        tmp_path, "# Personality\nname: Before\nemoji: 🥒\ntone: calm\nlanguage: en\n"
    )
    session = make_session(agent._config)

    msgs_before = agent._build_messages(session)
    sys_before = next(m.content for m in msgs_before if m.role == Role.SYSTEM)
    assert "Before" in sys_before

    pers_file = tmp_path / "personality" / "personality.md"
    pers_file.write_text(
        "# Personality\nname: After\nemoji: 🚀\ntone: energetic\nlanguage: en\n", encoding="utf-8"
    )

    msgs_after = agent._build_messages(session)
    sys_after = next(m.content for m in msgs_after if m.role == Role.SYSTEM)
    assert "After" in sys_after


def test_apply_personality_update_creates_backup(tmp_path):
    """apply_personality_update must backup personality.md.bak before overwriting."""
    from cucumber_agent.cli import apply_personality_update

    cfg = make_config(
        tmp_path, "# Personality\nname: Original\nemoji: 🥒\ntone: calm\nlanguage: en\n"
    )
    backup = tmp_path / "personality" / "personality.md.bak"
    assert not backup.exists()

    apply_personality_update({"emoji": "🚀", "tone": "energetic"}, cfg)

    assert backup.exists(), "Backup must be created during optimize"
    assert "Original" in backup.read_text(encoding="utf-8")
