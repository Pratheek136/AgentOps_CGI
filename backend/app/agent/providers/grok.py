"""Grok via xAI's OpenAI-compatible API (openai SDK with base_url)."""
from __future__ import annotations

import json
import os

from openai import OpenAI

from ...tools.registry import ToolSpec
from .base import LLMResponse, Provider, ProviderError, ToolCall

XAI_BASE_URL = "https://api.x.ai/v1"


class GrokProvider(Provider):
    name = "grok"

    def __init__(self, model: str) -> None:
        key = os.getenv("XAI_API_KEY", "")
        if not key or key.startswith("your-"):
            raise ProviderError("XAI_API_KEY is not set in .env")
        if not model or model.endswith("-here"):
            raise ProviderError("GROK_MODEL is not set in .env")
        self.model = model
        self._client = OpenAI(api_key=key, base_url=XAI_BASE_URL, timeout=120)

    @staticmethod
    def _tools(tools: list[ToolSpec]) -> list[dict]:
        return [{"type": "function", "function": {"name": t.name, "description": t.description,
                                                  "parameters": t.parameters}} for t in tools]

    @staticmethod
    def _messages(system: str, messages: list[dict]) -> list[dict]:
        out: list[dict] = [{"role": "system", "content": system}]
        for m in messages:
            if m["role"] == "user":
                out.append({"role": "user", "content": m["content"]})
            elif m["role"] == "assistant":
                msg: dict = {"role": "assistant", "content": m.get("content") or ""}
                if m.get("tool_calls"):
                    msg["tool_calls"] = [{"id": c["id"], "type": "function",
                                          "function": {"name": c["name"], "arguments": json.dumps(c["args"])}}
                                         for c in m["tool_calls"]]
                out.append(msg)
            elif m["role"] == "tool":
                out.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]})
        return out

    def chat(self, system: str, messages: list[dict], tools: list[ToolSpec]) -> LLMResponse:
        try:
            kwargs = {"tools": self._tools(tools), "tool_choice": "auto"} if tools else {}
            resp = self._client.chat.completions.create(
                model=self.model, messages=self._messages(system, messages), temperature=0.2, **kwargs)
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"Grok call failed: {type(exc).__name__}: {str(exc)[:300]}") from exc
        msg = resp.choices[0].message
        calls = []
        for tc in msg.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"_unparseable": tc.function.arguments}
            calls.append(ToolCall(tc.id, tc.function.name, args))
        return LLMResponse((msg.content or "").strip(), calls)
