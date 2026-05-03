"""Read file tool — reads file contents without shell approval."""

from __future__ import annotations

from pathlib import Path

from cucumber_agent.tools.base import BaseTool, ToolResult
from cucumber_agent.tools.registry import ToolRegistry


class ReadFileTool(BaseTool):
    name = "read_file"
    description = (
        "Liest den Inhalt einer Datei. Kein Shell-Befehl nötig. "
        "Nutze dieses Tool um Dateien zu lesen bevor du sie bearbeitest."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absoluter oder relativer Dateipfad",
            },
            "max_lines": {
                "type": "integer",
                "description": "Maximale Zeilenanzahl (Standard: 300)",
            },
        },
        "required": ["path"],
    }
    auto_approve = True

    async def execute(self, path: str, max_lines: int = 300) -> ToolResult:
        try:
            p = Path(path).expanduser().resolve()
            if not p.exists():
                return ToolResult(success=False, output="", error=f"Datei nicht gefunden: {path}")
            if not p.is_file():
                return ToolResult(success=False, output="", error=f"Kein reguläre Datei: {path}")

            content = p.read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines()
            truncated = False
            if len(lines) > max_lines:
                lines = lines[:max_lines]
                truncated = True

            result_text = "\n".join(lines)
            if truncated:
                result_text += (
                    f"\n... [{len(content.splitlines()) - max_lines} weitere Zeilen abgeschnitten]"
                )

            return ToolResult(success=True, output=result_text)
        except PermissionError:
            return ToolResult(success=False, output="", error=f"Zugriff verweigert: {path}")
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


ToolRegistry.register(ReadFileTool())
