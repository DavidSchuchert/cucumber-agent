"""Session and Message types."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Role(Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class ContentBlock:
    """A content block within a message."""

    type: str  # "text", "image", "tool_use", "tool_result"
    text: str | None = None
    name: str | None = None
    input: dict | None = None
    tool_use_id: str | None = None
    content: str | None = None
    mime_type: str | None = None


@dataclass
class ToolCall:
    """A tool call from the model."""

    id: str
    name: str
    input: dict


@dataclass
class Message:
    """A single message in a conversation."""

    role: Role
    content: str | list[ContentBlock]
    name: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class Session:
    """A conversation session."""

    id: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    messages: list[Message] = field(default_factory=list)
    model: str | None = None
    metadata: dict = field(default_factory=dict)

    def add_message(self, message: Message) -> None:
        """Append a message to the session."""
        self.messages.append(message)
        self.updated_at = datetime.utcnow()

    def add_user_message(self, content: str | list[ContentBlock]) -> None:
        """Add a user message."""
        self.add_message(Message(role=Role.USER, content=content))

    def add_assistant_message(self, content: str | list[ContentBlock]) -> None:
        """Add an assistant message."""
        self.add_message(Message(role=Role.ASSISTANT, content=content))

    def add_tool_result(
        self,
        tool_call_id: str,
        name: str,
        content: str,
    ) -> None:
        """Add a tool result message."""
        self.add_message(
            Message(
                role=Role.TOOL,
                content=content,
                name=name,
                tool_call_id=tool_call_id,
            )
        )
