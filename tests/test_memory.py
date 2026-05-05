"""Tests for the memory system — no information should be lost."""

from __future__ import annotations

import pytest
from conftest import make_config, make_mock_provider, make_session

from cucumber_agent.agent import Agent
from cucumber_agent.memory import FactsStore, SessionSummary, detect_learnable_facts
from cucumber_agent.session import Message, Role


def test_facts_store_persist_and_reload(tmp_path):
    """Facts written to FactsStore survive process restart (reload from disk)."""
    store = FactsStore(tmp_path / "facts.json")
    store.set("name", "David")
    store.set("wohnort", "Berlin")

    reloaded = FactsStore(tmp_path / "facts.json")
    assert reloaded.get("name") == "David"
    assert reloaded.get("wohnort") == "Berlin"


def test_facts_store_delete(tmp_path):
    store = FactsStore(tmp_path / "facts.json")
    store.set("key", "value")
    assert store.delete("key") is True
    assert store.get("key") is None
    assert store.delete("key") is False


def test_detect_learnable_facts_german():
    found = detect_learnable_facts("Ich heiße David und ich wohne in Berlin.")
    keys = [k for k, _ in found]
    assert "name" in keys
    assert "wohnort" in keys


def test_session_summary_save_and_load(tmp_path):
    """SessionSummary persists across instances."""
    store = SessionSummary(tmp_path / "summary.txt")
    store.save("User asked about weather in Berlin.")

    reloaded = SessionSummary(tmp_path / "summary.txt")
    content = reloaded.load()
    assert content is not None
    assert "weather" in content


def test_agent_loads_persistent_facts_without_session_metadata(tmp_path):
    """Persistent facts are injected even when live session metadata is empty."""
    cfg = make_config(tmp_path)
    FactsStore(cfg.memory.facts_file).set("projekt", "CucumberAgent")
    agent = Agent(provider=make_mock_provider(), config=cfg)
    session = make_session(cfg)

    messages = agent._build_messages(session)
    system_msg = next(m for m in messages if m.role == Role.SYSTEM)

    assert "Gemerkte Fakten:" in system_msg.content
    assert "projekt: CucumberAgent" in system_msg.content


def test_agent_preserves_active_memory_contexts(tmp_path):
    """Facts, pins, and historical summary all remain present in built messages."""
    cfg = make_config(tmp_path)
    agent = Agent(provider=make_mock_provider(), config=cfg)
    session = make_session(cfg)
    session.metadata["facts_context"] = "Gemerkte Fakten:\n  - name: David"
    session.metadata["pinned"] = "- Herbert Swarm muss perfekt laufen"
    session.metadata["summary"] = "Frühere Entscheidung: README neu strukturieren."

    messages = agent._build_messages(session)

    assert agent._validate_memory_context_preserved(session, messages) is True


@pytest.mark.asyncio
async def test_tui_compress_appends_summary(tmp_path):
    """TUI compression appends to existing summaries instead of replacing them."""
    from cucumber_agent.tui import CucumberTUI

    cfg = make_config(tmp_path)
    provider = make_mock_provider("New compact summary.")
    agent = Agent(provider=provider, config=cfg)
    tui = CucumberTUI(agent=agent, config=cfg)
    tui._session = make_session(cfg)
    tui._session.metadata["summary"] = "Existing TUI summary."

    for i in range(cfg.memory.max_session_messages):
        tui._session.messages.append(Message(role=Role.USER, content=f"message {i}"))

    await tui._maybe_compress()

    combined = tui._session.metadata.get("summary", "")
    assert "Existing TUI summary." in combined
    assert "New compact summary." in combined


@pytest.mark.asyncio
async def test_compress_appends_not_overwrites(tmp_path):
    """_maybe_compress_context must append to existing summary, not overwrite."""
    from cucumber_agent.agent import Agent

    cfg = make_config(tmp_path)
    provider = make_mock_provider("Summary of old messages.")
    agent = Agent(provider=provider, config=cfg)
    session = make_session(cfg)
    session.metadata["summary"] = "Existing previous summary."

    # Add enough messages to trigger compression (fill past the keep threshold)
    for i in range(cfg.memory.summarize_keep_recent + 2):
        session.messages.append(Message(role=Role.USER, content=f"message {i}"))

    await agent.compress_session(session)

    combined = session.metadata.get("summary", "")
    assert "Existing previous summary." in combined
    assert "Summary of old messages." in combined
