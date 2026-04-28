"""Agent - orchestrates providers, sessions, and tools."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from cucumber_agent.config import Config
from cucumber_agent.provider import BaseProvider, ModelResponse, ProviderRegistry
from cucumber_agent.providers import (
    minimax,      # noqa: F401
    openrouter,   # noqa: F401
    ollama,       # noqa: F401
)
from cucumber_agent.session import Message, Role, Session
from cucumber_agent.tools import ToolRegistry

if TYPE_CHECKING:
    pass


def estimate_tokens(text: str) -> int:
    """Rough estimate of tokens (1 token ≈ 4 chars)."""
    return len(text) // 4


def trim_messages(
    messages: list[Message],
    max_tokens: int,
    system_prompt_tokens: int,
) -> list[Message]:
    """Trim messages to fit within token budget, keeping the most recent."""
    budget = max_tokens - system_prompt_tokens - 200  # buffer

    if budget <= 0:
        return []

    total_tokens = sum(estimate_tokens(str(m.content)) for m in messages)
    if total_tokens <= budget:
        return messages

    # Keep most recent messages that fit in budget
    trimmed: list[Message] = []
    used_tokens = 0
    for msg in reversed(messages):
        msg_tokens = estimate_tokens(str(msg.content))
        if used_tokens + msg_tokens <= budget:
            trimmed.insert(0, msg)
            used_tokens += msg_tokens
        else:
            break

    return trimmed


# Greeting patterns for detecting first contact
GREETING_PATTERNS = [
    r"^hi\b", r"^hello\b", r"^hey\b", r"^yo\b", r"^sup\b",
    r"^moin\b", r"^servus\b", r"^hallo\b",
    r"^guten\s*morgen\b", r"^guten\s*tag\b", r"^grüß?e?\b",
]


def is_greeting(text: str) -> bool:
    """Check if text is a greeting."""
    text_lower = text.lower().strip()
    return any(re.match(p, text_lower) for p in GREETING_PATTERNS)


class Agent:
    """Core agent. Orchestrates provider calls and session management."""

    def __init__(self, provider: BaseProvider, config: Config):
        self._provider = provider
        self._config = config
        self._context_config = config.context
        self._agent_config = config.agent
        self._optimization_offered = False

    @classmethod
    def from_config(cls, config: Config | None = None) -> Agent:
        """Create an agent from configuration."""
        import os

        config = config or Config.load()
        provider_name = config.agent.provider
        provider_config = config.get_provider_config(provider_name)

        kwargs: dict = {}
        if provider_config:
            if provider_config.api_key:
                kwargs["api_key"] = provider_config.api_key
            if provider_config.base_url:
                kwargs["base_url"] = provider_config.base_url
            if provider_config.model:
                kwargs["model"] = provider_config.model

        env_key_map = {
            "openrouter": "OPENROUTER_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "nvidia_nim": "NVIDIA_NIM_API_KEY",
        }
        if provider_config and provider_config.api_key is None:
            env_var = env_key_map.get(provider_name)
            if env_var and env_var in os.environ:
                kwargs["api_key"] = os.environ[env_var]

        provider = ProviderRegistry.get(provider_name, **kwargs)
        return cls(provider=provider, config=config)

    def needs_optimization(self, user_input: str) -> bool:
        """Check if greeting and optimization hasn't been offered yet."""
        return not self._optimization_offered and is_greeting(user_input)

    def mark_optimization_offered(self) -> None:
        """Mark that optimization has been offered."""
        self._optimization_offered = True

    @property
    def personality(self):
        """Access personality config."""
        return self._config.personality

    def get_tools_spec(self) -> list[dict] | None:
        """Get tool specifications for the current provider."""
        from cucumber_agent.tools import ToolRegistry
        provider = self._config.agent.provider
        return ToolRegistry.get_tools_spec(provider)

    async def run(self, session: Session, user_input: str) -> str:
        """Process user input and return the response text."""
        session.add_user_message(user_input)
        messages = self._build_messages(session)
        tools = self.get_tools_spec()

        response = await self._provider.complete(
            messages=messages,
            model=self._agent_config.model,
            temperature=self._agent_config.temperature,
            max_tokens=self._agent_config.max_tokens,
            tools=tools if tools else None,
        )

        session.add_assistant_message(response.content)
        return response.content

    async def run_with_tools(self, session: Session, user_input: str) -> ModelResponse:
        """Process user input and return response with potential tool calls."""
        session.add_user_message(user_input)
        messages = self._build_messages(session)
        tools = self.get_tools_spec()

        response = await self._provider.complete(
            messages=messages,
            model=self._agent_config.model,
            temperature=self._agent_config.temperature,
            max_tokens=self._agent_config.max_tokens,
            tools=tools if tools else None,
        )

        # Don't add assistant message if tool calls present
        # The tool result will be added after execution
        if not response.tool_calls:
            session.add_assistant_message(response.content)

        return response

    async def compress_session(self, session: Session) -> None:
        """Compress old messages into a compact summary to save tokens.

        Keeps the most recent `remember_last` messages at full fidelity.
        Older messages are summarised and stored in session.metadata['summary'].
        The old messages are then removed from session.messages.
        """
        keep = self._context_config.remember_last
        if len(session.messages) <= keep:
            return

        old_messages = session.messages[:-keep]
        session.messages = session.messages[-keep:]

        # Build a minimal compression request (no tools, low temp)
        compression_system = (
            "Du fasst ein Gespräch präzise zusammen. "
            "Halte alle wichtigen Fakten, Ergebnisse, getroffene Entscheidungen "
            "und ausgeführte Befehle fest. Maximal 150 Wörter. Kein Smalltalk."
        )
        try:
            response = await self._provider.complete(
                messages=old_messages,
                model=self._agent_config.model,
                temperature=0.2,
                max_tokens=350,
                tools=None,
                system_override=compression_system,
            )
            new_summary = response.content.strip()
        except Exception:
            return  # Fail silently — better to lose compression than crash

        # Append to any existing summary
        existing = session.metadata.get("summary", "")
        if existing:
            session.metadata["summary"] = existing + "\n\n[Neuere Zusammenfassung:]\n" + new_summary
        else:
            session.metadata["summary"] = new_summary

    async def synthesize(self, session: Session, prompt: str = "", max_depth: int = 1) -> str:
        """Synthesize a response based on recent tool results in session."""
        # Build messages WITHOUT modifying session
        messages = []

        # Override system prompt to prevent tool calls
        system_override = (
            "Du fasst Tool-Ergebnisse für den Benutzer zusammen. "
            "Antworte direkt und klar. KEINE Werkzeug-Aufrufe mehr."
        )

        # Get full session context (respecting 3-tier memory)
        messages = self._build_messages(session)

        if prompt:
            messages.append(Message(role=Role.USER, content=prompt))

        # Use provider directly with system override to prevent tool calls
        response = await self._provider.complete(
            messages=messages,
            model=self._agent_config.model,
            temperature=self._agent_config.temperature,
            max_tokens=self._agent_config.max_tokens,
            tools=None,
            system_override=system_override,
        )

        return response.content

    async def run_stream(
        self,
        session: Session,
        user_input: str,
    ) -> AsyncIterator[str]:
        """Stream the response as chunks."""
        session.add_user_message(user_input)
        messages = self._build_messages(session)
        tools = self.get_tools_spec()

        if tools:
            # Use complete() to get response with potential tool calls
            response = await self._provider.complete(
                messages=messages,
                model=self._agent_config.model,
                temperature=self._agent_config.temperature,
                max_tokens=self._agent_config.max_tokens,
                tools=tools,
            )
            yield response.content
            session.add_assistant_message(response.content)

            # If tool calls present, return them for approval flow
            if response.tool_calls:
                return  # Caller should check session for tool calls
            return

        # No tools - use streaming
        full_response = ""
        stream_iter = self._provider.stream(
            messages=messages,
            model=self._agent_config.model,
            temperature=self._agent_config.temperature,
            max_tokens=self._agent_config.max_tokens,
        )
        async for chunk in stream_iter:
            full_response += chunk
            yield chunk

        session.add_assistant_message(full_response)

    def _build_messages(self, session: Session) -> list[Message]:
        """Build message list using 3-tier memory architecture.

        Tier 1 (Pinned — always present):
          - System prompt: personality + workspace + facts
        Tier 2 (Historical summary — if compression has run):
          - A single compressed summary of older messages
        Tier 3 (Recent messages — full fidelity):
          - Last `remember_last` messages
        """
        messages: list[Message] = []

        # ── Tier 1: Pinned system prompt ───────────────────────────────
        system_parts = [self._agent_config.system_prompt]

        if workspace := session.metadata.get("workspace"):
            system_parts.append(f"\n{workspace}")

        if facts := session.metadata.get("facts_context"):
            system_parts.append(f"\n{facts}")

        messages.append(Message(role=Role.SYSTEM, content="\n".join(system_parts)))

        # ── Tier 2: Historical summary ─────────────────────────────────
        if summary := session.metadata.get("summary"):
            messages.append(Message(
                role=Role.USER,
                content=f"[Gesprächszusammenfassung früherer Nachrichten:]\n{summary}",
            ))
            messages.append(Message(
                role=Role.ASSISTANT,
                content="Verstanden, ich berücksichtige den bisherigen Verlauf.",
            ))

        # ── Tier 3: Recent messages (never trimmed — compression handles this) ─
        remember_last = self._context_config.remember_last
        recent = session.messages[-remember_last:] if remember_last > 0 else session.messages
        messages.extend(recent)

        return messages
