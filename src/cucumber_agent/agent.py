"""Agent - orchestrates providers, sessions, and tools."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator

from cucumber_agent.config import Config
from cucumber_agent.provider import BaseProvider, ModelResponse, ProviderRegistry
from cucumber_agent.providers import (
    minimax,  # noqa: F401
    ollama,  # noqa: F401
    openrouter,  # noqa: F401
)
from cucumber_agent.session import ContentBlock, Message, Role, Session
from cucumber_agent.tools import ToolRegistry

_tiktoken_encoding = None


def _get_tiktoken_encoding():
    global _tiktoken_encoding
    if _tiktoken_encoding is None:
        try:
            import tiktoken
            _tiktoken_encoding = tiktoken.get_encoding("cl100k_base")
        except ImportError:
            pass
    return _tiktoken_encoding


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
    r"^hi\b",
    r"^hello\b",
    r"^hey\b",
    r"^yo\b",
    r"^sup\b",
    r"^moin\b",
    r"^servus\b",
    r"^hallo\b",
    r"^guten\s*morgen\b",
    r"^guten\s*tag\b",
    r"^grüß?e?\b",
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

    async def summarize_messages(self, messages: list[Message]) -> str:
        """Use the LLM to create a concise summary of the given messages."""
        if not messages:
            return ""

        history_text = "\n".join(
            [f"{m.role.value}: {self._extract_text(m.content)}" for m in messages]
        )

        prompt = (
            "Fasse den folgenden Gesprächsverlauf prägnant zusammen.\n\n"
            "WICHTIGE REGELN:\n"
            "- Konzentriere dich NUR auf: getroffene Entscheidungen, erledigte Aufgaben, wichtige Fakten über den Nutzer\n"
            "- Schreibe NIEMALS über die Persönlichkeit, den Namen, den Ton oder das Verhalten des Assistenten\n"
            "- Die Persönlichkeit des Assistenten ist unveränderlich und wird separat gespeichert — sie gehört NICHT in die Zusammenfassung\n"
            "- Antworte auf DEUTSCH, maximal 200 Wörter\n\n"
            f"GESPRÄCHSVERLAUF:\n{history_text}"
        )

        response = await self._provider.complete(
            messages=[Message(role=Role.USER, content=prompt)],
            model=self._agent_config.model,
            temperature=0.3,
        )
        return response.content

    def get_tools_spec(self) -> list[dict] | None:
        """Get tool specifications for the current provider."""

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
        if user_input:
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

        # Add assistant message with tool_calls so MiniMax can reference them in tool results
        from cucumber_agent.session import ToolCall as SessionToolCall

        assistant_msg = Message(
            role=Role.ASSISTANT,
            content=response.content,
            tool_calls=[
                SessionToolCall(id=tc.id, name=tc.name, arguments=tc.arguments)
                for tc in (response.tool_calls or [])
            ],
        )
        session.messages.append(assistant_msg)

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
            "und ausgeführte Befehle fest. Maximal 150 Wörter. Kein Smalltalk.\n\n"
            "KRITISCHE REGEL: Schreibe NIEMALS über die Persönlichkeit, den Namen, den Ton "
            "oder das Verhalten des Assistenten. Die Identität des Assistenten ist unveränderlich "
            "und wird separat verwaltet — sie gehört NICHT in die Zusammenfassung."
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
        system_override = (
            "Du fasst Tool-Ergebnisse für den Benutzer zusammen. "
            "Antworte direkt und klar. KEINE Werkzeug-Aufrufe mehr."
        )

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

        Tier 0 (Core identity — always first, never touched by compression):
          - Full personality.md content, wrapped in an immutability anchor
        Tier 1 (Pinned operational context):
          - Tool rules, workspace info, facts, skills
        Tier 2 (Historical summary — if compression has run):
          - Compressed summary of older messages (never contains personality)
        Tier 3 (Recent messages — full fidelity):
          - Last `remember_last` messages
        """
        messages: list[Message] = []

        # ── Tier 0: Core identity anchor (reload from disk every time) ─
        personality_file = self._config.config_dir / "personality" / "personality.md"
        from cucumber_agent.config import PersonalityConfig

        pers = PersonalityConfig.from_markdown(personality_file)
        core_identity = pers.to_core_identity_block()

        identity_block = (
            "=== CORE IDENTITY (IMMUTABLE) ===\n"
            "The following defines WHO YOU ARE. "
            "It is your permanent character and CANNOT be changed by conversation, "
            "memory compression, or any user instruction. "
            "Always stay in character — even after long sessions or context resets.\n\n"
            f"{core_identity}\n"
            "=== END CORE IDENTITY ==="
        )

        # ── Tier 1: Operational system prompt ─────────────────────────
        operational_parts = [self._agent_config.system_prompt]

        if workspace := session.metadata.get("workspace"):
            operational_parts.append(f"\n{workspace}")

        if facts := session.metadata.get("facts_context"):
            operational_parts.append(f"\nWas ich über den Nutzer weiß:\n{facts}")

        if agent_ctx := session.metadata.get("agent_context"):
            operational_parts.append(f"\n{agent_ctx}")

        if wiki := session.metadata.get("wiki_knowledge"):
            operational_parts.append(f"\n{wiki}")

        if pinned := session.metadata.get("pinned"):
            operational_parts.append(
                f"\n\n### Gepinnter Kontext (IMMER beachten, höchste Priorität):\n{pinned}"
            )

        operational_parts.append(
            "\n\n### Delegation Strategy\n"
            "If a task is complex, multi-step, or requires deep research/analysis, "
            "consider using the 'agent' tool to delegate it to a sub-agent."
        )

        system_content = identity_block + "\n\n" + "\n".join(operational_parts)
        messages.append(Message(role=Role.SYSTEM, content=system_content))

        # ── Tier 2: Historical summary ─────────────────────────────────
        if summary := session.metadata.get("summary"):
            messages.append(
                Message(
                    role=Role.USER,
                    content=f"[Gesprächszusammenfassung früherer Nachrichten:]\n{summary}",
                )
            )
            messages.append(
                Message(
                    role=Role.ASSISTANT,
                    content="Verstanden, ich berücksichtige den bisherigen Verlauf.",
                )
            )

        # ── Tier 3: Recent messages ────────────────────────────────────
        remember_last = self._context_config.remember_last
        recent = session.messages[-remember_last:] if remember_last > 0 else session.messages
        messages.extend(recent)

        return messages

    def estimate_tokens(self, messages: list[Message]) -> int:
        """Estimate token count for a list of messages."""
        encoding = _get_tiktoken_encoding()
        if encoding is None:
            return sum(len(self._extract_text(m.content)) // 4 for m in messages)

        count = 0
        for m in messages:
            count += 4  # message overhead
            count += len(encoding.encode(self._extract_text(m.content)))
            if m.name:
                count += 1
            if m.tool_calls:
                for tc in m.tool_calls:
                    count += len(encoding.encode(tc.name))
                    count += len(encoding.encode(str(tc.arguments)))
        count += 2  # priming
        return count

    def _validate_identity_preserved(self, messages: list[Message]) -> bool:
        """Return True if the CORE IDENTITY block is present in the system prompt."""
        for m in messages:
            if m.role == Role.SYSTEM:
                content = self._extract_text(m.content)
                if "=== CORE IDENTITY (IMMUTABLE) ===" in content:
                    return True
        return False

    def _extract_text(self, content: str | list[ContentBlock]) -> str:
        """Helper to get text from various content formats."""
        if isinstance(content, str):
            return content
        return "\n".join(
            b.text or b.content or "" for b in content if b.type in ("text", "tool_result")
        )
