"""Remember tool — lets the agent proactively store facts in long-term memory."""

from __future__ import annotations

import json
from pathlib import Path

from cucumber_agent.tools.base import BaseTool, ToolResult
from cucumber_agent.tools.registry import ToolRegistry

_FACTS_FILE = Path.home() / ".cucumber" / "memory" / "facts.json"


class RememberTool(BaseTool):
    name = "remember"
    description = (
        "Speichert einen wichtigen Fakt dauerhaft im Langzeitgedächtnis. "
        "Nutze dieses Tool wenn der Benutzer persönliche Informationen teilt "
        "(Name, Beruf, Präferenzen, laufende Projekte) oder explizit sagt "
        "'merk dir', 'vergiss nicht', 'ich bin', 'ich arbeite an'."
    )
    parameters = {
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "Kurzer Schlüssel (z.B. 'name', 'job', 'aktuelles_projekt')",
            },
            "value": {
                "type": "string",
                "description": "Der zu merkende Wert",
            },
        },
        "required": ["key", "value"],
    }
    auto_approve = True

    async def execute(self, key: str, value: str) -> ToolResult:
        try:
            _FACTS_FILE.parent.mkdir(parents=True, exist_ok=True)
            facts: dict = {}
            if _FACTS_FILE.exists():
                try:
                    facts = json.loads(_FACTS_FILE.read_text(encoding="utf-8"))
                except Exception:
                    facts = {}

            norm_key = key.strip().lower().replace(" ", "_")
            facts[norm_key] = value.strip()
            _FACTS_FILE.write_text(
                json.dumps(facts, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return ToolResult(success=True, output=f"✓ Gemerkt: {norm_key} = {value}")
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


ToolRegistry.register(RememberTool())
