"""Agent - orchestrates providers, sessions, and tools."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from cucumber_agent.config import Config
from cucumber_agent.provider import BaseProvider, ProviderRegistry

# Import providers to trigger @ProviderRegistry.register decorators
from cucumber_agent.providers import (
    minimax,  # noqa: F401
    openrouter,  # noqa: F401
)
from cucumber_agent.session import Message, Role, Session

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
    """Trim messages to fit within token budget."""
    budget = max_tokens - system_prompt_tokens - 200  # buffer

    if budget <= 0:
        return []

    # Calculate current tokens
    current_tokens = sum(estimate_tokens(str(m.content)) for m in messages)

    if current_tokens <= budget:
        return messages

    # Keep last N messages if remember_last is set
    # Start from the end and work backwards
    trimmed: list[Message] = []
    for msg in reversed(messages):
        msg_tokens = estimate_tokens(str(msg.content))
        if current_tokens + msg_tokens <= budget:
            trimmed.insert(0, msg)
            current_tokens += msg_tokens
        else:
            break

    return trimmed


# Emoji suggestions based on name patterns
EMOJI_MAP = {
    "cucumber": "🥒", "gherkin": "🥒", "pickle": "🥒",
    "herb": "🌿", "sage": "🧙", "mint": "🍃", "thyme": "🌱",
    "buddy": "🤝", "friend": "😊", "pal": "🙂", "max": "🎯",
    "claude": "🧠", "atlas": "🌍", "neo": "🕶️", "cipher": "🔐",
    "code": "💻", "bit": "🖥️", "byte": "⚡", "chip": "🔧",
    "pixel": "🖼️", "debug": "🐛", "syntax": "📝",
    "blob": "🟢", "wizard": "🧙‍♂️", "mage": "✨", "nova": "⭐",
    "echo": "🔊", "sigma": "∑", "omega": "Ω", "delta": "Δ",
    "arc": "🌈", "flux": "⚡", "zen": "☯️",
}

GREETING_PATTERNS = [
    r"^hi\b", r"^hello\b", r"^hey\b", r"^yo\b", r"^sup\b",
    r"^moin\b", r"^servus\b", r"^hallo\b", r"^moin\b",
    r"^guten\s*morgen\b", r"^guten\s*tag\b", r"^grüß?e?\b",
]


def is_greeting(text: str) -> bool:
    """Check if text is a greeting."""
    text_lower = text.lower().strip()
    for pattern in GREETING_PATTERNS:
        if re.match(pattern, text_lower):
            return True
    return False


def suggest_emoji(name: str) -> str:
    """Suggest emoji based on agent name."""
    name_lower = name.lower()
    for key, emoji in EMOJI_MAP.items():
        if key in name_lower:
            return emoji
    return "🤖"


def suggest_optimization(name: str, tone: str, greeting: str) -> dict:
    """Suggest personality optimizations based on name."""
    emoji = suggest_emoji(name)

    # Suggest greeting based on tone
    tone_greetings = {
        "casual": f"Hey! Ich bin {name}. Was geht? 😎",
        "friendly": f"Hi! Freut mich, dich zu sehen! Ich bin {name}. 👋",
        "professional": f"Guten Tag. Ich bin {name}. Wie kann ich Ihnen helfen?",
        "formal": f"Mein Name ist {name}. Zu Ihren Diensten.",
    }
    suggested_greeting = tone_greetings.get(tone, greeting)

    # Suggest strengths based on name keywords
    name_keywords = {
        "code": "programming, debugging, code review, software architecture",
        "herb": "research, writing, analysis, knowledge synthesis",
        "sage": "wisdom, problem-solving, strategic thinking",
        "buddy": "support, collaboration, communication, encouragement",
        "claude": "reasoning, analysis, writing, creative problem-solving",
        "nova": "creativity, innovation, exploration, inspiration",
        "zen": "mindfulness, clarity, simplicity, balance",
    }

    suggested_strengths = "coding, problem-solving, research, communication"
    for key, strengths in name_keywords.items():
        if key in name.lower():
            suggested_strengths = strengths
            break

    return {
        "emoji": emoji,
        "greeting": suggested_greeting,
        "strengths": suggested_strengths,
    }


class Agent:
    """
    Core agent. Orchestrates provider calls and session management.
    Does NOT handle CLI or networking directly.
    """

    def __init__(
        self,
        provider: BaseProvider,
        config: Config,
    ):
        self._provider = provider
        self._config = config
        self._context_config = config.context
        self._agent_config = config.agent
        self._optimization_offered = False  # Track if optimization was offered

    @classmethod
    def from_config(cls, config: Config | None = None) -> Agent:
        """Create an agent from configuration."""
        import os

        config = config or Config.load()
        provider_name = config.agent.provider
        provider_config = config.get_provider_config(provider_name)

        # Build kwargs from config
        kwargs: dict = {}
        if provider_config:
            if provider_config.api_key:
                kwargs["api_key"] = provider_config.api_key
            if provider_config.base_url:
                kwargs["base_url"] = provider_config.base_url
            if provider_config.model:
                kwargs["model"] = provider_config.model

        # Check env vars as fallback
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
        """Check if this is a greeting and optimization hasn't been offered yet."""
        if self._optimization_offered:
            return False
        return is_greeting(user_input)

    def build_optimization_response(self, user_input: str) -> str:
        """Build response offering optimization after first greeting."""
        pers = self._config.personality
        suggestions = suggest_optimization(pers.name, pers.tone, pers.greeting)

        # Check if already optimized (has emoji set and different from default)
        current_emoji = pers.emoji if pers.emoji else "🤖"
        already_optimized = (
            pers.greeting and pers.greeting != f"Hi! I'm {pers.name}. How can I help you today?"
        )

        if already_optimized:
            return ""  # Skip optimization offer

        self._optimization_offered = True

        return (
            f"\n\n_{current_emoji} psst! Ich könnte meine Persönlichkeit noch "
            f'etwas optimieren basierend auf meinem Namen "{pers.name}"..._\n\n'
            f"Soll ich das tun? (Schlag vor: Emoji {suggestions['emoji']}, "
            f"passenderes Greeting, passende Stärken)\n\n"
            f'Antworte einfach **"ja"** oder **"nein"**!'
        )

    def apply_optimization(self) -> dict:
        """Apply suggested optimizations to personality.md."""
        pers = self._config.personality
        suggestions = suggest_optimization(pers.name, pers.tone, pers.greeting)

        # Update config in memory
        pers.emoji = suggestions["emoji"]
        pers.greeting = suggestions["greeting"]
        pers.strengths = suggestions["strengths"]

        # Save to personality.md
        pers.to_markdown(self._config.config_dir / "personality" / "personality.md")

        # Also update system prompt in config.yaml
        self._agent_config.system_prompt = pers.to_system_prompt()
        self._config.save()

        return suggestions

    async def run(self, session: Session, user_input: str) -> str:
        """Process user input and return the response text."""
        session.add_user_message(user_input)
        messages = self._build_messages(session)

        response = await self._provider.complete(
            messages=messages,
            model=self._agent_config.model,
            temperature=self._agent_config.temperature,
            max_tokens=self._agent_config.max_tokens,
        )

        session.add_assistant_message(response.content)
        return response.content

    async def run_stream(
        self,
        session: Session,
        user_input: str,
    ) -> AsyncIterator[str]:
        """Stream the response as chunks."""
        session.add_user_message(user_input)
        messages = self._build_messages(session)

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
        """Build the message list for the provider with context trimming."""
        messages = []

        # Add system prompt
        system_prompt = self._agent_config.system_prompt
        if system_prompt:
            messages.append(
                Message(
                    role=Role.SYSTEM,
                    content=system_prompt,
                )
            )

        system_tokens = estimate_tokens(system_prompt)
        max_tokens = self._context_config.max_tokens

        # Get conversation history
        history = session.messages

        # Apply remember_last if set
        remember_last = self._context_config.remember_last
        if remember_last > 0 and len(history) > remember_last:
            # Keep only last N messages
            history = history[-remember_last:]

        # Trim to fit token budget
        if history:
            trimmed_history = trim_messages(history, max_tokens, system_tokens)
            messages.extend(trimmed_history)

        return messages
