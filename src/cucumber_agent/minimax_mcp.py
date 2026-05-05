"""MiniMax Token Plan MCP client.

The official Token Plan MCP server exposes web_search and understand_image via
stdio JSON-RPC. This module keeps the integration dependency-free and starts the
server only for the duration of one tool call.
"""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cucumber_agent.config import Config


class MiniMaxMCPError(RuntimeError):
    """Raised when the MiniMax MCP server cannot be used."""


@dataclass(frozen=True)
class MiniMaxMCPConfig:
    """Runtime settings for the MiniMax MCP stdio server."""

    command: str
    args: tuple[str, ...]
    env: dict[str, str]
    timeout: float = 120.0


def _normalize_api_host(base_url: str | None) -> str:
    """Return the host expected by MiniMax MCP, without API compatibility suffixes."""
    if not base_url:
        return "https://api.minimax.io"
    host = base_url.rstrip("/")
    for suffix in ("/v1", "/anthropic"):
        if host.endswith(suffix):
            host = host[: -len(suffix)]
    return host or "https://api.minimax.io"


def resolve_minimax_api_key(config: Config | None = None) -> str | None:
    """Resolve the MiniMax API key from env first, then config."""
    if api_key := os.environ.get("MINIMAX_API_KEY"):
        return api_key
    try:
        config = config or Config.load()
        provider_cfg = config.get_provider_config("minimax")
        return provider_cfg.api_key if provider_cfg else None
    except Exception:
        return None


def build_minimax_mcp_config(
    config: Config | None = None,
    *,
    timeout: float = 120.0,
) -> MiniMaxMCPConfig:
    """Build MCP server command/env from Cucumber config and environment."""
    config = config or Config.load()
    provider_cfg = config.get_provider_config("minimax")
    api_key = resolve_minimax_api_key(config)
    if not api_key:
        raise MiniMaxMCPError("MINIMAX_API_KEY fehlt für MiniMax MCP.")

    command = os.environ.get("MINIMAX_MCP_COMMAND", "uvx")
    args = tuple(shlex.split(os.environ.get("MINIMAX_MCP_ARGS", "minimax-coding-plan-mcp -y")))
    api_host = os.environ.get(
        "MINIMAX_API_HOST",
        _normalize_api_host(provider_cfg.base_url if provider_cfg else None),
    )

    env = os.environ.copy()
    env["MINIMAX_API_KEY"] = api_key
    env["MINIMAX_API_HOST"] = api_host

    if base_path := os.environ.get("MINIMAX_MCP_BASE_PATH"):
        Path(base_path).expanduser().mkdir(parents=True, exist_ok=True)
        env["MINIMAX_MCP_BASE_PATH"] = str(Path(base_path).expanduser())
    if resource_mode := os.environ.get("MINIMAX_API_RESOURCE_MODE"):
        env["MINIMAX_API_RESOURCE_MODE"] = resource_mode

    return MiniMaxMCPConfig(command=command, args=args, env=env, timeout=timeout)


def minimax_mcp_command_available(command: str | None = None) -> bool:
    """Return True if the MCP launcher command is available."""
    command = command or os.environ.get("MINIMAX_MCP_COMMAND", "uvx")
    if os.sep in command:
        return Path(command).expanduser().exists()
    return shutil.which(command) is not None


def minimax_mcp_mode() -> str:
    """Return MCP routing mode: auto, always, or never."""
    mode = os.environ.get("CUCUMBER_MINIMAX_MCP", "auto").strip().lower()
    aliases = {
        "1": "always",
        "true": "always",
        "yes": "always",
        "on": "always",
        "0": "never",
        "false": "never",
        "no": "never",
        "off": "never",
        "disabled": "never",
        "disable": "never",
    }
    return aliases.get(mode, mode if mode in {"auto", "always", "never"} else "auto")


def should_use_minimax_mcp(config: Config | None = None) -> bool:
    """Return True when MiniMax MCP should be attempted for a tool call."""
    mode = minimax_mcp_mode()
    if mode == "never":
        return False
    if mode == "always":
        return True

    try:
        config = config or Config.load()
    except Exception:
        return False
    return (
        config.agent.provider == "minimax"
        and resolve_minimax_api_key(config) is not None
        and minimax_mcp_command_available()
    )


def can_try_minimax_mcp(config: Config | None = None) -> bool:
    """Return True when the MCP server can be attempted independent of active provider."""
    mode = minimax_mcp_mode()
    if mode == "never":
        return False
    if mode == "always":
        return True
    try:
        config = config or Config.load()
    except Exception:
        config = None
    return resolve_minimax_api_key(config) is not None and minimax_mcp_command_available()


def minimax_mcp_diagnostic(config: Config) -> tuple[str, str]:
    """Return doctor status/detail for MiniMax MCP."""
    mode = minimax_mcp_mode()
    if mode == "never":
        return "[dim]AUS[/dim]", "CUCUMBER_MINIMAX_MCP=never"
    api_key = resolve_minimax_api_key(config)
    command = os.environ.get("MINIMAX_MCP_COMMAND", "uvx")
    if not api_key:
        return "[yellow]HINWEIS[/yellow]", "MINIMAX_API_KEY fehlt"
    if not minimax_mcp_command_available(command):
        return "[yellow]HINWEIS[/yellow]", f"{command} nicht gefunden"
    if mode == "always":
        return "[green]OK[/green]", f"{command} minimax-coding-plan-mcp (erzwungen)"
    detail = "aktiv" if config.agent.provider == "minimax" else "bereit, wenn Provider minimax ist"
    return "[green]OK[/green]", f"{command} minimax-coding-plan-mcp ({detail})"


async def call_minimax_mcp_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    config: Config | None = None,
    timeout: float = 120.0,
) -> str:
    """Call one MiniMax MCP tool and return flattened text content."""
    mcp_config = build_minimax_mcp_config(config, timeout=timeout)
    if not minimax_mcp_command_available(mcp_config.command):
        raise MiniMaxMCPError(f"MCP-Kommando nicht gefunden: {mcp_config.command}")

    client = _MiniMaxMCPStdioClient(mcp_config)
    try:
        await client.start()
        await client.initialize()
        result = await client.call_tool(name, arguments)
        return extract_mcp_text(result)
    finally:
        await client.close()


def extract_mcp_text(result: dict[str, Any]) -> str:
    """Flatten MCP tool result content into a readable string."""
    if result.get("isError"):
        text = _extract_content_blocks(result.get("content", []))
        raise MiniMaxMCPError(text or "MiniMax MCP meldete einen Tool-Fehler.")
    return _extract_content_blocks(result.get("content", [])) or json.dumps(
        result,
        ensure_ascii=False,
        indent=2,
    )


def _extract_content_blocks(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text" and block.get("text"):
            parts.append(str(block["text"]))
        elif block.get("type") in {"image", "resource"}:
            parts.append(json.dumps(block, ensure_ascii=False))
    return "\n".join(parts).strip()


class _MiniMaxMCPStdioClient:
    """Small JSON-RPC client for one MiniMax MCP stdio subprocess."""

    def __init__(self, config: MiniMaxMCPConfig) -> None:
        self._config = config
        self._process: asyncio.subprocess.Process | None = None
        self._next_id = 1

    async def start(self) -> None:
        self._process = await asyncio.create_subprocess_exec(
            self._config.command,
            *self._config.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._config.env,
        )

    async def initialize(self) -> None:
        await self._request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "cucumber-agent", "version": "0.1.0"},
            },
        )
        await self._notify("notifications/initialized", {})

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self._request(
            "tools/call",
            {"name": name, "arguments": arguments},
        )

    async def close(self) -> None:
        process = self._process
        if process is None:
            return
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=2)
            except TimeoutError:
                process.kill()
                await process.wait()

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        await self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})

        while True:
            message = await asyncio.wait_for(self._read_message(), timeout=self._config.timeout)
            if message.get("id") != request_id:
                continue
            if error := message.get("error"):
                raise MiniMaxMCPError(str(error))
            result = message.get("result", {})
            if not isinstance(result, dict):
                raise MiniMaxMCPError(f"Unerwartete MCP-Antwort: {result!r}")
            return result

    async def _notify(self, method: str, params: dict[str, Any]) -> None:
        await self._send({"jsonrpc": "2.0", "method": method, "params": params})

    async def _send(self, payload: dict[str, Any]) -> None:
        process = self._require_process()
        if process.stdin is None:
            raise MiniMaxMCPError("MCP stdin ist nicht verfügbar.")
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        process.stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
        await process.stdin.drain()

    async def _read_message(self) -> dict[str, Any]:
        process = self._require_process()
        if process.stdout is None:
            raise MiniMaxMCPError("MCP stdout ist nicht verfügbar.")
        headers = await self._read_headers(process.stdout)
        length_text = headers.get("content-length")
        if not length_text:
            raise MiniMaxMCPError(f"MCP-Antwort ohne Content-Length: {headers}")
        body = await process.stdout.readexactly(int(length_text))
        return json.loads(body.decode("utf-8"))

    async def _read_headers(self, reader: asyncio.StreamReader) -> dict[str, str]:
        raw = b""
        while b"\r\n\r\n" not in raw and b"\n\n" not in raw:
            chunk = await reader.read(1)
            if not chunk:
                stderr = await self._read_stderr()
                raise MiniMaxMCPError(f"MCP-Server geschlossen. {stderr}".strip())
            raw += chunk
        header_text = raw.decode("ascii", errors="replace")
        headers: dict[str, str] = {}
        for line in header_text.replace("\r\n", "\n").split("\n"):
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            headers[key.strip().lower()] = value.strip()
        return headers

    async def _read_stderr(self) -> str:
        process = self._require_process()
        if process.stderr is None:
            return ""
        try:
            data = await asyncio.wait_for(process.stderr.read(4000), timeout=0.2)
        except TimeoutError:
            return ""
        return data.decode("utf-8", errors="replace").strip()

    def _require_process(self) -> asyncio.subprocess.Process:
        if self._process is None:
            raise MiniMaxMCPError("MCP-Server wurde nicht gestartet.")
        return self._process
