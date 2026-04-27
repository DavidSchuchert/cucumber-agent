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

        workspace = data.get("workspace")
        if workspace:
            workspace = Path(workspace)

        return cls(
            config_dir=config_dir,
            providers=providers,
            agent=agent,
            workspace=workspace,
        )

    def save(self) -> None:
        """Save configuration to YAML file."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        config_file = self.config_dir / "config.yaml"

        data = {
            "agent": {
                "provider": self.agent.provider,
                "model": self.agent.model,
                "temperature": self.agent.temperature,
                "max_tokens": self.agent.max_tokens,
                "system_prompt": self.agent.system_prompt,
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
