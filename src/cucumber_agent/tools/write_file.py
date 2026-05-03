"""Write file tool — creates or overwrites a file."""

from __future__ import annotations

from pathlib import Path

from cucumber_agent.tools.base import BaseTool, ToolResult
from cucumber_agent.tools.registry import ToolRegistry


class WriteFileTool(BaseTool):
    name = "write_file"
    description = (
        "Erstellt oder überschreibt eine Datei mit dem angegebenen Inhalt. "
        "Für kleine Änderungen bevorzuge 'shell' mit sed/awk."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Dateipfad (wird erstellt falls nicht vorhanden)",
            },
            "content": {
                "type": "string",
                "description": "Der zu schreibende Inhalt",
            },
            "mode": {
                "type": "string",
                "description": "'write' (überschreiben, Standard) oder 'append' (anhängen)",
                "enum": ["write", "append"],
            },
            "reason": {
                "type": "string",
                "description": "Kurze Erklärung warum diese Datei geschrieben wird",
            },
        },
        "required": ["path", "content"],
    }
    auto_approve = False

    async def execute(
        self,
        path: str,
        content: str,
        mode: str = "write",
        reason: str = "",
    ) -> ToolResult:
        try:
            p = Path(path).expanduser()
            p.parent.mkdir(parents=True, exist_ok=True)

            if mode == "append":
                with open(p, "a", encoding="utf-8") as f:
                    f.write(content)
                action = "angehängt"
            else:
                p.write_text(content, encoding="utf-8")
                action = "geschrieben"

            return ToolResult(
                success=True,
                output=f"✓ {len(content)} Zeichen nach {path} {action}",
            )
        except PermissionError:
            return ToolResult(success=False, output="", error=f"Zugriff verweigert: {path}")
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


ToolRegistry.register(WriteFileTool())
