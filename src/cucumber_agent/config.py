"""Configuration system - YAML-based config with env override."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_DIR = Path.home() / ".cucumber"


@dataclass
class ProviderConfig:
    """Configuration for a single provider."""

    name: str
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class PersonalityConfig:
    """Agent personality configuration."""

    name: str = "Cucumber"
    emoji: str = "🤖"
    tone: str = "friendly"
    language: str = "en"
    greeting: str = ""
    strengths: str = ""
    interests: str = ""

    @classmethod
    def from_markdown(cls, path: Path) -> PersonalityConfig:
        """Load from personality.md file."""
        if not path.exists():
            return cls()

        content = path.read_text()
        data = cls._parse_md_dict(content)
        return cls(
            name=data.get("name", "Cucumber"),
            emoji=data.get("emoji", "🤖"),
            tone=data.get("tone", "friendly"),
            language=data.get("language", "en"),
            greeting=data.get("greeting", ""),
            strengths=data.get("strengths", ""),
            interests=data.get("interests", ""),
        )

    @staticmethod
    def _parse_md_dict(content: str) -> dict[str, str]:
        """Parse markdown key: value pairs."""
        result: dict[str, str] = {}
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ": " in line:
                key, value = line.split(": ", 1)
                result[key.strip()] = value.strip()
            elif ":" in line:
                key, value = line.split(":", 1)
                result[key.strip()] = value.strip()
        return result

    def to_markdown(self, path: Path) -> None:
        """Save to personality.md file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# Personality",
            f"name: {self.name}",
            f"emoji: {self.emoji}",
            f"tone: {self.tone}",
            f"language: {self.language}",
            f"greeting: {self.greeting}",
            f"strengths: {self.strengths}",
            f"interests: {self.interests}",
            "",
        ]
        path.write_text("\n".join(lines))

    def to_system_prompt(self) -> str:
        """Build system prompt from personality."""
        parts = []

        lang = self.language or "en"
        lang_map = {"en": "English", "de": "German"}
        language_name = lang_map.get(lang, lang)
        parts.append(
            f"I ALWAYS communicate in {language_name}. ALL my responses must be in {language_name}."
        )

        parts.append(f"My name is {self.name}.")

        tone_desc = {
            "casual": "I'm casual and relaxed in my communication.",
            "friendly": "I'm warm and friendly in my communication.",
            "professional": "I'm professional and concise in my communication.",
            "formal": "I'm formal and respectful in my communication.",
        }
        parts.append(tone_desc.get(self.tone, f"I communicate in a {self.tone} manner."))

        if self.greeting:
            parts.append(f'My typical greeting is: "{self.greeting}"')

        if self.strengths:
            parts.append(f"My strengths include: {self.strengths}.")

        if self.interests:
            parts.append(f"I'm particularly interested in: {self.interests}.")

        parts.append("I'm here to help my human with whatever they need!")

        return " ".join(parts)


@dataclass
class UserConfig:
    """User information."""

    name: str = ""
    bio: str = ""
    github: str = ""
    portfolio: str = ""


@dataclass
class PreferencesConfig:
    """Agent behavior preferences."""

    can_search_web: bool = True
    can_code: bool = True
    can_remember: bool = True


@dataclass
class ContextConfig:
    """Context/memory settings."""

    max_tokens: int = 8000
    remember_last: int = 10


@dataclass
class AgentConfig:
    """Main agent configuration."""

    provider: str = "openrouter"
    model: str = "openai/gpt-4o-mini"
    temperature: float = 0.7
    max_tokens: int | None = None
    system_prompt: str = "You are CucumberAgent, a helpful AI assistant."


@dataclass
class Config:
    """Main configuration object."""

    config_dir: Path = field(default_factory=lambda: DEFAULT_CONFIG_DIR)
    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    agent: AgentConfig = field(default_factory=AgentConfig)
    personality: PersonalityConfig = field(default_factory=PersonalityConfig)
    user: UserConfig = field(default_factory=UserConfig)
    preferences: PreferencesConfig = field(default_factory=PreferencesConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    workspace: Path | None = None

    @classmethod
    def load(cls, config_dir: Path | None = None) -> Config:
        """Load configuration from YAML file."""
        config_dir = config_dir or DEFAULT_CONFIG_DIR
        config_file = config_dir / "config.yaml"

        if not config_file.exists():
            return cls(config_dir=config_dir)

        with open(config_file) as f:
            data = yaml.safe_load(f) or {}

        # Load providers
        providers = {}
        for name, pdata in data.get("providers", {}).items():
            if isinstance(pdata, dict):
                providers[name] = ProviderConfig(
                    name=name,
                    api_key=pdata.get("api_key"),
                    base_url=pdata.get("base_url"),
                    model=pdata.get("model"),
                    extra=pdata.get("extra", {}),
                )

        # Load agent config
        agent_data = data.get("agent", {})
        agent = AgentConfig(
            provider=agent_data.get("provider", "openrouter"),
            model=agent_data.get("model", "openai/gpt-4o-mini"),
            temperature=agent_data.get("temperature", 0.7),
            max_tokens=agent_data.get("max_tokens"),
            system_prompt=agent_data.get(
                "system_prompt",
                "You are CucumberAgent, a helpful AI assistant.",
            ),
        )

        # Load personality from personality.md (new structured approach)
        personality = PersonalityConfig.from_markdown(
            config_dir / "personality" / "personality.md"
        )

        # Load user info from user.md (new structured approach)
        user_md = config_dir / "user" / "user.md"
        if user_md.exists():
            user_data = PersonalityConfig._parse_md_dict(user_md.read_text())
            user = UserConfig(
                name=user_data.get("name", ""),
                bio=user_data.get("bio", ""),
                github=user_data.get("github", ""),
                portfolio=user_data.get("portfolio", ""),
            )
        else:
            # Fallback to YAML for backwards compatibility
            user_data = data.get("user", {})
            user = UserConfig(
                name=user_data.get("name", ""),
                bio=user_data.get("bio", ""),
                github=user_data.get("github", ""),
                portfolio=user_data.get("portfolio", ""),
            )

        # Load preferences
        pref_data = data.get("preferences", {})
        preferences = PreferencesConfig(
            can_search_web=pref_data.get("can_search_web", True),
            can_code=pref_data.get("can_code", True),
            can_remember=pref_data.get("can_remember", True),
        )

        # Load context
        ctx_data = data.get("context", {})
        context = ContextConfig(
            max_tokens=ctx_data.get("max_tokens", 8000),
            remember_last=ctx_data.get("remember_last", 10),
        )

        # Load workspace
        workspace = data.get("workspace")
        if workspace:
            workspace = Path(workspace)

        return cls(
            config_dir=config_dir,
            providers=providers,
            agent=agent,
            personality=personality,
            user=user,
            preferences=preferences,
            context=context,
            workspace=workspace,
        )

    def save(self) -> None:
        """Save configuration to YAML file."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        config_file = self.config_dir / "config.yaml"

        # Save personality to personality.md
        self.personality.to_markdown(self.config_dir / "personality" / "personality.md")

        # Save user to user.md
        user_md = self.config_dir / "user" / "user.md"
        user_md.parent.mkdir(parents=True, exist_ok=True)
        user_lines = [
            "# User",
            f"name: {self.user.name}",
            f"bio: {self.user.bio}",
            f"github: {self.user.github}",
            f"portfolio: {self.user.portfolio}",
            "",
        ]
        user_md.write_text("\n".join(user_lines))

        data = {
            "agent": {
                "provider": self.agent.provider,
                "model": self.agent.model,
                "temperature": self.agent.temperature,
                "max_tokens": self.agent.max_tokens,
                "system_prompt": self.personality.to_system_prompt(),
            },
            "providers": {
                name: {
                    "api_key": p.api_key,
                    "base_url": p.base_url,
                    "model": p.model,
                    "extra": p.extra,
                }
                for name, p in self.providers.items()
            },
            # personality now in ~/.cucumber/personality/personality.md
            # user now in ~/.cucumber/user/user.md
            "preferences": {
                "can_search_web": self.preferences.can_search_web,
                "can_code": self.preferences.can_code,
                "can_remember": self.preferences.can_remember,
            },
            "context": {
                "max_tokens": self.context.max_tokens,
                "remember_last": self.context.remember_last,
            },
        }

        if self.workspace:
            data["workspace"] = str(self.workspace)

        with open(config_file, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    def get_provider_config(self, name: str) -> ProviderConfig | None:
        """Get provider config by name."""
        return self.providers.get(name)


def ensure_config_dir() -> Path:
    """Ensure config directory exists."""
    config_dir = DEFAULT_CONFIG_DIR
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_default_provider() -> tuple[str, ProviderConfig]:
    """Get the default provider from config or environment."""
    config = Config.load()
    provider_name = config.agent.provider
    provider_config = config.get_provider_config(provider_name)

    # Check environment for API key
    if provider_config and provider_config.api_key is None:
        env_key_map = {
            "openrouter": "OPENROUTER_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "nvidia_nim": "NVIDIA_NIM_API_KEY",
        }
        env_var = env_key_map.get(provider_name)
        if env_var:
            api_key = os.environ.get(env_var)
            if api_key:
                return provider_name, ProviderConfig(
                    name=provider_name,
                    api_key=api_key,
                    base_url=provider_config.base_url,
                    model=provider_config.model,
                )

    return provider_name, provider_config or ProviderConfig(name=provider_name)
