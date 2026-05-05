"""Image understanding tool using MiniMax API."""

from __future__ import annotations

import httpx

from cucumber_agent.minimax_mcp import (
    MiniMaxMCPError,
    call_minimax_mcp_tool,
    can_try_minimax_mcp,
    minimax_mcp_mode,
)
from cucumber_agent.tools.base import BaseTool, ToolResult
from cucumber_agent.tools.registry import ToolRegistry

_SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
_MAX_IMAGE_BYTES = 20 * 1024 * 1024


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
        """Analyze an image using MiniMax MCP, with legacy API fallback."""
        validation_error = _validate_image_reference(image_url)
        if validation_error:
            return ToolResult(success=False, output="", error=validation_error)

        if can_try_minimax_mcp():
            try:
                output = await call_minimax_mcp_tool(
                    "understand_image",
                    {"prompt": prompt, "image_url": image_url},
                )
                return ToolResult(success=True, output=output)
            except MiniMaxMCPError as exc:
                if minimax_mcp_mode() == "always":
                    return ToolResult(
                        success=False,
                        output="",
                        error=(
                            "MiniMax MCP understand_image fehlgeschlagen. "
                            "Prüfe `uvx`, `MINIMAX_API_KEY` und `MINIMAX_API_HOST`. "
                            f"Details: {exc}"
                        ),
                    )

        return await self._execute_legacy_chat_vision(prompt, image_url)

    async def _execute_legacy_chat_vision(self, prompt: str, image_url: str) -> ToolResult:
        """Fallback image analysis via MiniMax OpenAI-compatible chat endpoint."""
        import os

        # Try env var first, then fall back to config
        api_key = os.environ.get("MINIMAX_API_KEY")
        if not api_key:
            from cucumber_agent.config import Config

            config = Config.load()
            prov_cfg = config.get_provider_config("minimax")
            if prov_cfg and prov_cfg.api_key:
                api_key = prov_cfg.api_key

        if not api_key:
            return ToolResult(
                success=False,
                output="",
                error="MINIMAX_API_KEY nicht gesetzt. Bitte in config.yaml oder als Environment Variable setzen.",
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
                    mime_map = {
                        ".jpg": "image/jpeg",
                        ".jpeg": "image/jpeg",
                        ".png": "image/png",
                        ".gif": "image/gif",
                        ".webp": "image/webp",
                    }
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
                                    {"type": "image_url", "image_url": {"url": image_url}},
                                ],
                            }
                        ],
                        "max_tokens": 1000,
                    },
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


def _validate_image_reference(image_url: str) -> str | None:
    """Validate local image references before sending them to MiniMax MCP/API."""
    if image_url.startswith(("http://", "https://")):
        return None

    from pathlib import Path

    path = Path(image_url.replace("file://", "")).expanduser()
    if not path.exists():
        return f"Bild nicht gefunden: {path}"
    if path.suffix.lower() not in _SUPPORTED_EXTENSIONS:
        return "Unsupported image format. Erlaubt: JPEG, PNG, GIF, WebP."
    if path.stat().st_size > _MAX_IMAGE_BYTES:
        return "Bild ist größer als 20MB; MiniMax MCP unterstützt maximal 20MB."
    return None


# Register the tool
ToolRegistry.register(UnderstandImageTool())
