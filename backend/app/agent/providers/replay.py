"""Records real LLM exchanges and replays them offline, in order, per scenario."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from ...config import paths
from ...security import mask
from ...tools.registry import ToolSpec
from .base import LLMResponse, Provider, ProviderError, ToolCall

log = logging.getLogger("rootfix.replay")


def scenario_dir(scenario: str) -> Path:
    return paths.replays / scenario


class RecordingProvider(Provider):
    """Wraps a real provider and saves each request/response to fixtures/replays/<scenario>/<step>.json."""

    def __init__(self, inner: Provider, scenario: str) -> None:
        self.inner, self.scenario = inner, scenario
        self.name, self.model = f"{inner.name}+record", inner.model
        self.dir = scenario_dir(scenario)
        if self.dir.exists():
            for f in self.dir.glob("*.json"):
                f.unlink()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.step = 0

    def chat(self, system: str, messages: list[dict], tools: list[ToolSpec]) -> LLMResponse:
        resp = self.inner.chat(system, messages, tools)
        self.step += 1
        last = messages[-3:] if messages else []
        record = {
            "scenario": self.scenario, "step": self.step, "provider": self.inner.name, "model": self.inner.model,
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "request_tail": [{"role": m["role"], "content": mask(str(m.get("content") or ""))[:1500],
                              "tool_calls": m.get("tool_calls")} for m in last],
            "response": resp.to_json(),
        }
        (self.dir / f"{self.step:03d}.json").write_text(json.dumps(record, indent=2, ensure_ascii=False),
                                                        encoding="utf-8")
        return resp


class ReplayProvider(Provider):
    name = "replay"

    def __init__(self, scenario: str) -> None:
        self.scenario = scenario
        self.model = f"replay:{scenario}"
        self.files = sorted(scenario_dir(scenario).glob("*.json"))
        if not self.files:
            raise ProviderError(f"no replay fixtures in fixtures/replays/{scenario}/ (record them first)")
        self.step = 0

    def chat(self, system: str, messages: list[dict], tools: list[ToolSpec]) -> LLMResponse:
        if self.step >= len(self.files):
            raise ProviderError(f"replay for {self.scenario} exhausted after {self.step} steps")
        rec = json.loads(self.files[self.step].read_text(encoding="utf-8"))
        self.step += 1
        time.sleep(0.8)  # keep the UI readable
        r = rec["response"]
        return LLMResponse(r.get("text", ""), [ToolCall(c["id"], c["name"], c["args"]) for c in r.get("tool_calls", [])])
