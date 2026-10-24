"""Provider factory."""
from __future__ import annotations

from ...config import llm_config
from .base import LLMResponse, Provider, ProviderError, ToolCall


def make_provider(scenario: str, provider: str | None = None) -> Provider:
    cfg = llm_config()
    name = (provider or cfg["provider"]).lower()
    if name == "replay":
        from .replay import ReplayProvider
        return ReplayProvider(cfg["scenario"] or scenario)
    if name == "gemini":
        from .gemini import GeminiProvider
        p: Provider = GeminiProvider(cfg["gemini_model"])
    elif name == "grok":
        from .grok import GrokProvider
        p = GrokProvider(cfg["grok_model"])
    else:
        raise ProviderError(f"unknown LLM_PROVIDER {name!r}")
    if cfg["record"]:
        from .replay import RecordingProvider
        return RecordingProvider(p, scenario)
    return p


__all__ = ["LLMResponse", "Provider", "ProviderError", "ToolCall", "make_provider"]
