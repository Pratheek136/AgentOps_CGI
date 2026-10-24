"""Gemini via the google-genai SDK (native function calling, manual loop)."""
from __future__ import annotations

import os
import uuid

from google import genai
from google.genai import types

from ...tools.registry import ToolSpec
from .base import LLMResponse, Provider, ProviderError, ToolCall


class GeminiProvider(Provider):
    name = "gemini"

    def __init__(self, model: str) -> None:
        key = os.getenv("GEMINI_API_KEY", "")
        if not key or key.startswith("your-"):
            raise ProviderError("GEMINI_API_KEY is not set in .env")
        if not model or model.endswith("-here"):
            raise ProviderError("GEMINI_MODEL is not set in .env")
        self.model = model
        self._client = genai.Client(api_key=key)

    def _tools(self, tools: list[ToolSpec]) -> list[types.Tool]:
        decls = []
        for t in tools:
            kw = {"name": t.name, "description": t.description}
            if t.parameters.get("properties"):
                kw["parameters_json_schema"] = t.parameters
            decls.append(types.FunctionDeclaration(**kw))
        return [types.Tool(function_declarations=decls)]

    def _contents(self, messages: list[dict]) -> list[types.Content]:
        out: list[types.Content] = []
        pending_responses: list[types.Part] = []

        def flush() -> None:
            if pending_responses:
                out.append(types.Content(role="user", parts=list(pending_responses)))
                pending_responses.clear()

        for m in messages:
            if m["role"] == "tool":
                pending_responses.append(types.Part.from_function_response(
                    name=m["name"], response={"result": m["content"]}))
                continue
            flush()
            if m["role"] == "user":
                out.append(types.Content(role="user", parts=[types.Part.from_text(text=m["content"])]))
            elif m["role"] == "assistant":
                if isinstance(m.get("native"), types.Content):
                    out.append(m["native"])  # verbatim: keeps thought signatures
                else:
                    parts = []
                    if m.get("content"):
                        parts.append(types.Part.from_text(text=m["content"]))
                    for c in m.get("tool_calls", []):
                        parts.append(types.Part(function_call=types.FunctionCall(name=c["name"], args=c["args"])))
                    out.append(types.Content(role="model", parts=parts))
        flush()
        return out

    def chat(self, system: str, messages: list[dict], tools: list[ToolSpec]) -> LLMResponse:
        config = types.GenerateContentConfig(
            system_instruction=system,
            tools=self._tools(tools) if tools else None,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            temperature=0.2,
        )
        try:
            resp = self._client.models.generate_content(model=self.model, contents=self._contents(messages),
                                                        config=config)
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"Gemini call failed: {type(exc).__name__}: {str(exc)[:300]}") from exc
        cand = (resp.candidates or [None])[0]
        if cand is None or cand.content is None:
            return LLMResponse(text="")
        text, calls = [], []
        for p in cand.content.parts or []:
            if p.function_call:
                calls.append(ToolCall(p.function_call.id or f"call_{uuid.uuid4().hex[:8]}",
                                      p.function_call.name, dict(p.function_call.args or {})))
            elif p.text and not getattr(p, "thought", False):
                text.append(p.text)
        return LLMResponse("\n".join(text).strip(), calls, native=cand.content)
