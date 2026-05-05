"""Tests for SQLite-backed memory: SQLiteFactsStore and structured SessionLogger."""

from __future__ import annotations

from pathlib import Path

from cucumber_agent.memory import (
    FactsStore,
    SessionLogger,
    SQLiteFactsStore,
)

# ---------------------------------------------------------------------------
# SQLiteFactsStore tests
# ---------------------------------------------------------------------------


def test_sqlite_facts_store_auto_dispatch(tmp_path: Path) -> None:
    """FactsStore returns SQLiteFactsStore when path ends in .db."""
    store = FactsStore(tmp_path / "facts.db")
    assert isinstance(store, SQLiteFactsStore)


def test_sqlite_facts_store_set_and_get(tmp_path: Path) -> None:
    """Basic set/get round-trip is persisted immediately."""
    store = SQLiteFactsStore(tmp_path / "facts.db")
    store.set("name", "David")
    store.set("wohnort", "Berlin")

    assert store.get("name") == "David"
    assert store.get("wohnort") == "Berlin"
    assert store.get("nonexistent") is None


def test_sqlite_facts_store_persist_across_instances(tmp_path: Path) -> None:
    """Data survives closing and reopening the store (new instance)."""
    db = tmp_path / "facts.db"

    store1 = SQLiteFactsStore(db)
    store1.set("sprache", "Deutsch")
    store1.set("projekt", "cucumber-agent")
    store1.close()

    store2 = SQLiteFactsStore(db)
    assert store2.get("sprache") == "Deutsch"
    assert store2.get("projekt") == "cucumber-agent"
    store2.close()


def test_sqlite_facts_store_delete(tmp_path: Path) -> None:
    """delete() removes the key and returns True; second call returns False."""
    store = SQLiteFactsStore(tmp_path / "facts.db")
    store.set("temp", "remove me")

    assert store.delete("temp") is True
    assert store.get("temp") is None
    assert store.delete("temp") is False


def test_sqlite_facts_store_all(tmp_path: Path) -> None:
    """all() returns a plain dict with all stored entries."""
    store = SQLiteFactsStore(tmp_path / "facts.db")
    store.set("a", "1")
    store.set("b", "2")
    store.set("c", "3")

    result = store.all()
    assert result == {"a": "1", "b": "2", "c": "3"}


def test_sqlite_facts_store_update_existing_key(tmp_path: Path) -> None:
    """Setting an existing key updates its value (upsert semantics)."""
    store = SQLiteFactsStore(tmp_path / "facts.db")
    store.set("city", "Hamburg")
    store.set("city", "Berlin")
    assert store.get("city") == "Berlin"
    # Only one row should exist for this key
    assert len(store.all()) == 1


def test_sqlite_facts_store_to_context_string(tmp_path: Path) -> None:
    """to_context_string returns a non-empty formatted string when facts exist."""
    store = SQLiteFactsStore(tmp_path / "facts.db")
    assert store.to_context_string() == ""

    store.set("name", "Alice")
    ctx = store.to_context_string()
    assert "Gemerkte Fakten:" in ctx
    assert "name: Alice" in ctx


def test_sqlite_facts_store_add_from_text_key_value(tmp_path: Path) -> None:
    """add_from_text parses 'key: value' syntax."""
    store = SQLiteFactsStore(tmp_path / "facts.db")
    key = store.add_from_text("hobby: Lesen")
    assert key == "hobby"
    assert store.get("hobby") == "Lesen"


def test_sqlite_facts_store_add_from_text_plain_note(tmp_path: Path) -> None:
    """add_from_text stores plain text as a timestamped note."""
    store = SQLiteFactsStore(tmp_path / "facts.db")
    key = store.add_from_text("remember to update tests")
    assert key.startswith("notiz_")
    assert store.get(key) == "remember to update tests"


def test_json_facts_store_still_works(tmp_path: Path) -> None:
    """FactsStore with .json path still returns the original JSON-backed class."""
    store = FactsStore(tmp_path / "facts.json")
    assert not isinstance(store, SQLiteFactsStore)
    store.set("key", "val")
    assert store.get("key") == "val"

    # Reload from disk
    store2 = FactsStore(tmp_path / "facts.json")
    assert store2.get("key") == "val"


# ---------------------------------------------------------------------------
# SessionLogger structured logging tests
# ---------------------------------------------------------------------------


def test_session_logger_structured_write_and_query(tmp_path: Path) -> None:
    """log_exchange with structured=True is queryable via get_recent_summary_structured."""
    logger = SessionLogger(tmp_path / "logs")
    logger.log_exchange("Hello", "Hi there!", structured=True)
    logger.log_exchange("What time is it?", "It is noon.", tools_used=["clock"], structured=True)

    summary = logger.get_recent_summary_structured(hours=1)
    assert "Hello" in summary
    assert "Hi there!" in summary
    assert "What time is it?" in summary
    assert "clock" in summary


def test_session_logger_structured_empty_when_no_db(tmp_path: Path) -> None:
    """get_recent_summary_structured returns empty string if no DB exists yet."""
    logger = SessionLogger(tmp_path / "logs")
    # No structured=True writes — DB file should not exist
    result = logger.get_recent_summary_structured()
    assert result == ""


def test_session_logger_structured_max_entries(tmp_path: Path) -> None:
    """get_recent_summary_structured respects max_entries limit."""
    logger = SessionLogger(tmp_path / "logs")
    for i in range(10):
        logger.log_exchange(f"q{i}", f"a{i}", structured=True)

    summary = logger.get_recent_summary_structured(hours=1, max_entries=3)
    # Count occurrences of "**Du:**" to verify entry count
    assert summary.count("**Du:**") == 3


def test_session_logger_markdown_unaffected_when_structured_false(tmp_path: Path) -> None:
    """Writing without structured=True still writes markdown and no DB file."""
    log_dir = tmp_path / "logs"
    logger = SessionLogger(log_dir)
    logger.log_exchange("ping", "pong", structured=False)

    # Markdown file should exist
    md_files = list(log_dir.glob("*.md"))
    assert len(md_files) == 1
    assert "ping" in md_files[0].read_text(encoding="utf-8")

    # DB should not have been created (structured=False)
    db_path = log_dir / "exchanges.db"
    # The DB may or may not exist; if it exists, the table should be empty
    if db_path.exists():
        import sqlite3

        conn = sqlite3.connect(str(db_path))
        count = conn.execute("SELECT COUNT(*) FROM exchanges").fetchone()[0]
        conn.close()
        assert count == 0


def test_session_logger_structured_respects_hours_cutoff(tmp_path: Path) -> None:
    """Exchanges outside the hours window are excluded from structured summary."""
    import sqlite3

    log_dir = tmp_path / "logs"
    logger = SessionLogger(log_dir)
    # Write one entry the normal way
    logger.log_exchange("recent", "fresh answer", structured=True)

    # Manually backdating an entry by inserting directly
    old_ts = "2000-01-01T00:00:00"
    conn = sqlite3.connect(str(log_dir / "exchanges.db"))
    conn.execute(
        "INSERT INTO exchanges (ts, user_input, response, tools_used) VALUES (?,?,?,?)",
        (old_ts, "ancient question", "ancient answer", None),
    )
    conn.commit()
    conn.close()

    summary = logger.get_recent_summary_structured(hours=1)
    assert "recent" in summary
    assert "ancient question" not in summary
