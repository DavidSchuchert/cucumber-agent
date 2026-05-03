"""Memory system: session logging and persistent facts store."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path


class SessionLogger:
    """Appends each exchange to a daily markdown log file."""

    def __init__(self, log_dir: Path | str) -> None:
        self._log_dir = Path(log_dir)  # ensure Path
        self._log_dir.mkdir(parents=True, exist_ok=True)

    def _today_file(self) -> Path:
        today = datetime.now().strftime("%Y-%m-%d")
        return self._log_dir / f"{today}.md"

    def log_exchange(
        self,
        user_input: str,
        response: str,
        tools_used: list[str] | None = None,
    ) -> None:
        """Append one exchange to today's log."""
        f = self._today_file()
        ts = datetime.now().strftime("%H:%M")
        short_resp = response[:150].replace("\n", " ") + ("…" if len(response) > 150 else "")

        lines = [f"\n## {ts}", f"**Du:** {user_input}", f"**Agent:** {short_resp}"]
        if tools_used:
            lines.append(f"**Tools:** {', '.join(tools_used)}")

        with open(f, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")

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


class FactsStore:
    """Persistent JSON store for important facts about the user / context."""

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

    def get(self, key: str) -> str | None:
        return self._facts.get(key.strip().lower().replace(" ", "_"))

    def set(self, key: str, value: str) -> None:
        self._facts[key.strip().lower().replace(" ", "_")] = value.strip()
        self._save()

    def delete(self, key: str) -> bool:
        key = key.strip().lower().replace(" ", "_")
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
        for sep in (": ", " = ", ": "):
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
