"""Provider interface: chat(system, messages, tools) -> LLMResponse.

Neutral message format:
  {"role": "user", "content": str}
  {"role": "assistant", "content": str | None, "tool_calls": [{"id", "name", "args"}], "native": <opaque>}
  {"role": "tool", "tool_call_id": str, "name": str, "content": str}
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ...tools.registry import ToolSpec


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    native: Any = None  # provider-specific assistant turn, sent back verbatim next time

    def to_message(self) -> dict:
        return {"role": "assistant", "content": self.text or None,
                "tool_calls": [{"id": c.id, "name": c.name, "args": c.args} for c in self.tool_calls],
                "native": self.native}

    def to_json(self) -> dict:
        return {"text": self.text, "tool_calls": [{"id": c.id, "name": c.name, "args": c.args} for c in self.tool_calls]}


class ProviderError(Exception):
    pass


class Provider(ABC):
    name: str = "base"
    model: str = ""

    @abstractmethod
    def chat(self, system: str, messages: list[dict], tools: list[ToolSpec]) -> LLMResponse: ...
