"""Tests for the memory system — no information should be lost."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from cucumber_agent.memory import FactsStore, SessionSummary, detect_learnable_facts
from cucumber_agent.session import Message, Role

from conftest import make_config, make_mock_provider, make_session


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
