"""Memory system: session logging and persistent facts store."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

# Patterns that suggest learnable user facts
_LEARN_PATTERNS = [
    (r"\bich hei(?:ße|sse)\s+(\w+)", "name"),
    (r"\bmein name ist\s+(\w+)", "name"),
    (r"\bcall me\s+(\w+)", "name"),
    (r"\bich bin\s+(\d+)\s+jahre?", "alter"),
    (r"\bich wohne in\s+([^,.!?]+)", "wohnort"),
    (r"\bich arbeite (?:als|bei)\s+([^,.!?]+)", "beruf"),
    (r"\bich mag\s+(?:lieber\s+)?([^,.!?]+)", "vorliebe"),
    (r"\bich bevorzuge\s+([^,.!?]+)", "vorliebe"),
    (r"\bmein projekt (?:heißt|ist)\s+([^,.!?]+)", "projekt"),
]


def detect_learnable_facts(text: str) -> list[tuple[str, str]]:
    """Scan user text for facts worth remembering. Returns [(key, value)]."""
    found: list[tuple[str, str]] = []
    text_lower = text.lower()
    for pattern, key in _LEARN_PATTERNS:
        m = re.search(pattern, text_lower)
        if m:
            value = m.group(1).strip().rstrip(".,!?")
            found.append((key, value))
    return found


# ---------------------------------------------------------------------------
# Session DB helper (shared connection factory)
# ---------------------------------------------------------------------------

_SESSION_SCHEMA = """
CREATE TABLE IF NOT EXISTS exchanges (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    user_input  TEXT NOT NULL,
    response    TEXT NOT NULL,
    tools_used  TEXT
);
"""


def _open_session_db(path: Path) -> sqlite3.Connection:
    """Open (and initialize) the structured session SQLite database."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute(_SESSION_SCHEMA)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# SessionLogger
# ---------------------------------------------------------------------------


class SessionLogger:
    """Appends each exchange to a daily markdown log file.

    If *structured=True* is passed to ``log_exchange`` the exchange is also
    written to a SQLite database alongside the markdown files so that
    ``get_recent_summary_structured`` can return results without file-parsing.
    """

    def __init__(self, log_dir: Path | str) -> None:
        self._log_dir = Path(log_dir)  # ensure Path
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = self._log_dir / "exchanges.db"
        self._conn: sqlite3.Connection | None = None

    def _today_file(self) -> Path:
        today = datetime.now().strftime("%Y-%m-%d")
        return self._log_dir / f"{today}.md"

    def _get_conn(self) -> sqlite3.Connection:
        """Return (lazily opened) structured DB connection."""
        if self._conn is None:
            self._conn = _open_session_db(self._db_path)
        return self._conn

    def log_exchange(
        self,
        user_input: str,
        response: str,
        tools_used: list[str] | None = None,
        *,
        structured: bool = False,
    ) -> None:
        """Append one exchange to today's log.

        Args:
            user_input: The user's message.
            response: The agent's response.
            tools_used: Optional list of tool names used in this exchange.
            structured: If True, also write to the SQLite database.
        """
        f = self._today_file()
        ts = datetime.now().strftime("%H:%M")
        short_resp = response[:150].replace("\n", " ") + ("…" if len(response) > 150 else "")

        lines = [f"\n## {ts}", f"**Du:** {user_input}", f"**Agent:** {short_resp}"]
        if tools_used:
            lines.append(f"**Tools:** {', '.join(tools_used)}")

        with open(f, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")

        if structured:
            conn = self._get_conn()
            ts_full = datetime.now().isoformat(timespec="seconds")
            tools_json = json.dumps(tools_used, ensure_ascii=False) if tools_used else None
            conn.execute(
                "INSERT INTO exchanges (ts, user_input, response, tools_used) VALUES (?,?,?,?)",
                (ts_full, user_input, response, tools_json),
            )
            conn.commit()

    def get_recent_summary(self, days: int = 2, max_entries: int = 8) -> str:
        """Return compact text of recent log entries (for context injection)."""
        entries: list[str] = []
        for i in range(days):
            date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            log_file = self._log_dir / f"{date}.md"
            if not log_file.exists():
                continue
            content = log_file.read_text(encoding="utf-8")
            current: list[str] = []
            day_entries: list[str] = []
            for line in content.splitlines():
                if line.startswith("## "):
                    if current:
                        day_entries.append("\n".join(current))
                    current = [line]
                elif current:
                    current.append(line)
            if current:
                day_entries.append("\n".join(current))
            entries.extend(day_entries[-max_entries:])
            if len(entries) >= max_entries:
                break
        return "\n".join(entries[:max_entries]) if entries else ""

    def get_recent_summary_structured(
        self,
        hours: int = 48,
        max_entries: int = 8,
    ) -> str:
        """Return compact text of recent exchanges from the SQLite database.

        Uses SQL instead of file-parsing.  Falls back to an empty string if
        no structured data has been written yet.

        Args:
            hours: How many hours back to look.
            max_entries: Maximum number of exchanges to return.
        """
        if not self._db_path.exists():
            return ""
        conn = self._get_conn()
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat(timespec="seconds")
        rows = conn.execute(
            "SELECT ts, user_input, response, tools_used "
            "FROM exchanges WHERE ts >= ? ORDER BY ts DESC LIMIT ?",
            (cutoff, max_entries),
        ).fetchall()

        if not rows:
            return ""

        parts: list[str] = []
        for row in reversed(rows):
            ts_str = row["ts"][11:16]  # HH:MM from ISO string
            short_resp = row["response"][:150].replace("\n", " ")
            if len(row["response"]) > 150:
                short_resp += "…"
            entry = f"## {ts_str}\n**Du:** {row['user_input']}\n**Agent:** {short_resp}"
            if row["tools_used"]:
                tools = json.loads(row["tools_used"])
                entry += f"\n**Tools:** {', '.join(tools)}"
            parts.append(entry)

        return "\n".join(parts)

    def close(self) -> None:
        """Close the SQLite connection if open."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None


# ---------------------------------------------------------------------------
# FactsStore (JSON-based, original)
# ---------------------------------------------------------------------------


class FactsStore:
    """Persistent JSON store for important facts about the user / context.

    When ``facts_file`` ends with ``.db`` a :class:`SQLiteFactsStore` is
    returned instead (see :func:`FactsStore.__new__`).
    """

    def __new__(cls, facts_file: Path | str) -> FactsStore:  # type: ignore[misc]
        path = Path(facts_file)
        if path.suffix.lower() == ".db" and cls is FactsStore:
            return object.__new__(SQLiteFactsStore)
        return object.__new__(cls)

    def __init__(self, facts_file: Path | str) -> None:
        self._file = Path(facts_file)  # ensure Path
        self._file.parent.mkdir(parents=True, exist_ok=True)
        self._facts: dict[str, str] = self._load()

    def _load(self) -> dict[str, str]:
        if self._file.exists():
            try:
                return json.loads(self._file.read_text(encoding="utf-8"))
            except Exception:
                return {}
        # Ensure the file exists for later saves
        self._file.parent.mkdir(parents=True, exist_ok=True)
        self._file.write_text("{}", encoding="utf-8")
        return {}

    def _save(self) -> None:
        self._file.write_text(
            json.dumps(self._facts, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _normalize(key: str) -> str:
        return key.strip().lower().replace(" ", "_")

    def get(self, key: str) -> str | None:
        return self._facts.get(self._normalize(key))

    def set(self, key: str, value: str) -> None:
        self._facts[self._normalize(key)] = value.strip()
        self._save()

    def delete(self, key: str) -> bool:
        key = self._normalize(key)
        if key in self._facts:
            del self._facts[key]
            self._save()
            return True
        return False

    def all(self) -> dict[str, str]:
        return dict(self._facts)

    def add_from_text(self, text: str) -> str:
        """
        Parse '/remember key: value' or '/remember key = value'.
        Otherwise stores the whole text as a timestamped note.
        Returns the key under which it was saved.
        """
        text = text.strip()
        for sep in (": ", " = "):
            if sep in text:
                key, _, value = text.partition(sep)
                self.set(key, value)
                return key.strip()
        # Plain note
        key = f"notiz_{datetime.now().strftime('%H%M%S')}"
        self.set(key, text)
        return key

    def to_context_string(self) -> str:
        """Compact string injected into the system prompt's pinned context."""
        if not self._facts:
            return ""
        lines = ["Gemerkte Fakten:"]
        for key, value in self._facts.items():
            lines.append(f"  - {key}: {value}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# SQLiteFactsStore
# ---------------------------------------------------------------------------

_FACTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class SQLiteFactsStore(FactsStore):
    """SQLite-backed variant of :class:`FactsStore`.

    Activated automatically when the *facts_file* path ends with ``.db``.
    Exposes the same interface as :class:`FactsStore`.
    """

    def __init__(self, facts_file: Path | str) -> None:
        self._file = Path(facts_file)
        self._file.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._file))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_FACTS_SCHEMA)
        self._conn.commit()

    # Override in-memory dict operations with SQL ----------------------------

    def get(self, key: str) -> str | None:
        key = self._normalize(key)
        row = self._conn.execute("SELECT value FROM facts WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set(self, key: str, value: str) -> None:
        key = self._normalize(key)
        value = value.strip()
        now = datetime.now().isoformat(timespec="seconds")
        self._conn.execute(
            "INSERT INTO facts (key, value, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, value, now),
        )
        self._conn.commit()

    def delete(self, key: str) -> bool:
        key = self._normalize(key)
        cursor = self._conn.execute("DELETE FROM facts WHERE key = ?", (key,))
        self._conn.commit()
        return cursor.rowcount > 0

    def all(self) -> dict[str, str]:
        rows = self._conn.execute("SELECT key, value FROM facts ORDER BY key").fetchall()
        return {row["key"]: row["value"] for row in rows}

    def to_context_string(self) -> str:
        """Compact string injected into the system prompt's pinned context."""
        facts = self.all()
        if not facts:
            return ""
        lines = ["Gemerkte Fakten:"]
        for key, value in facts.items():
            lines.append(f"  - {key}: {value}")
        return "\n".join(lines)

    # JSON-specific methods are no-ops / not used ----------------------------

    def _load(self) -> dict[str, str]:  # type: ignore[override]
        return {}  # not used — DB is the source of truth

    def _save(self) -> None:
        pass  # not used — every write goes directly to SQLite

    def add_from_text(self, text: str) -> str:
        """Same parsing logic as FactsStore, but persists via SQLite."""
        text = text.strip()
        for sep in (": ", " = "):
            if sep in text:
                key, _, value = text.partition(sep)
                self.set(key, value)
                return key.strip()
        key = f"notiz_{datetime.now().strftime('%H%M%S')}"
        self.set(key, text)
        return key

    def close(self) -> None:
        """Close the SQLite connection."""
        self._conn.close()


# ---------------------------------------------------------------------------
# SessionSummary
# ---------------------------------------------------------------------------


class SessionSummary:
    """Persistent storage for the latest session summary."""

    def __init__(self, summary_file: Path | str) -> None:
        self._file = Path(summary_file)  # ensure Path
        self._file.parent.mkdir(parents=True, exist_ok=True)

    def save(self, summary: str) -> None:
        """Save a new summary to disk."""
        self._file.write_text(summary.strip(), encoding="utf-8")

    def load(self) -> str | None:
        """Load the latest summary from disk."""
        if self._file.exists():
            return self._file.read_text(encoding="utf-8")
        return None
