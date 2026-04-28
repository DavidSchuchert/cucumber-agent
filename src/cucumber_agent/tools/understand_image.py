"""Image understanding tool using MiniMax API."""

from __future__ import annotations

import httpx

from cucumber_agent.tools.base import BaseTool, ToolResult
from cucumber_agent.tools.registry import ToolRegistry


class UnderstandImageTool(BaseTool):
    """Analyze and understand images using MiniMax's vision API."""

    name = "understand_image"
    description = (
        "Analysiert ein Bild und beschreibt dessen Inhalt. "
        "Nutze dieses Tool wenn der Benutzer ein Bild beschrieben haben möchte, "
        "einen Screenshot erklärt haben möchte, oder Fragen zu einem Bild hat."
    )
    parameters = {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Die Frage oder Anweisung zum Bild (z.B. 'Beschreibe was auf dem Bild ist', 'Was ist der Inhalt?')",
            },
            "image_url": {
                "type": "string",
                "description": "URL des Bildes (HTTP/HTTPS) oder lokaler Dateipfad",
            },
        },
        "required": ["prompt", "image_url"],
    }

    async def execute(self, prompt: str, image_url: str) -> ToolResult:
        """Analyze an image using MiniMax API."""
        import os

        api_key = os.environ.get("MINIMAX_API_KEY")
        if not api_key:
            return ToolResult(
                success=False,
                output="",
                error="MINIMAX_API_KEY nicht gesetzt. Bitte in config.yaml oder als Environment Variable setzen."
            )

        # If it's a local file, read it and convert to base64
        if image_url.startswith(("file://", "/", "~")) or not image_url.startswith("http"):
            import base64
            from pathlib import Path

            path = Path(image_url.replace("file://", ""))
            if path.expanduser().exists():
                with open(path.expanduser(), "rb") as f:
                    image_data = base64.b64encode(f.read()).decode()
                    # Determine mime type from extension
                    ext = path.suffix.lower()
                    mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp"}
                    mime = mime_map.get(ext, "image/jpeg")
                    image_url = f"data:{mime};base64,{image_data}"
            else:
                return ToolResult(success=False, output="", error=f"Bild nicht gefunden: {path}")

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    "https://api.minimax.io/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "MiniMax-M2.7",
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": prompt},
                                    {"type": "image_url", "image_url": {"url": image_url}}
                                ]
                            }
                        ],
                        "max_tokens": 1000,
                    }
                )
                resp.raise_for_status()
                data = resp.json()

            # Extract response
            choices = data.get("choices", [{}])
            content = choices[0].get("message", {}).get("content", "")
            if content:
                return ToolResult(success=True, output=content)
            else:
                return ToolResult(success=True, output="Keine Bildbeschreibung erhalten.")

        except httpx.TimeoutException:
            return ToolResult(success=False, output="", error="Bildanalyse Timeout (60s).")
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


# Register the tool
ToolRegistry.register(UnderstandImageTool())