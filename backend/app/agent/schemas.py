"""Typed views of agent decisions and attempts (validated dicts come from tools.registry)."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Hypothesis:
    cause: str
    confidence: float
    evidence: list[str]


@dataclass
class Decision:
    hypotheses: list[Hypothesis]
    chosen_action: str
    rationale: str
    expected_effect: str
    risk: str

    @classmethod
    def from_dict(cls, d: dict) -> "Decision":
        return cls([Hypothesis(**h) for h in d["hypotheses"]], d["chosen_action"], d["rationale"],
                   d.get("expected_effect", ""), d.get("risk", ""))

    @property
    def top(self) -> Hypothesis:
        return max(self.hypotheses, key=lambda h: h.confidence)

    @property
    def evidence(self) -> list[str]:
        seen: list[str] = []
        for h in self.hypotheses:
            for e in h.evidence:
                if e not in seen:
                    seen.append(e)
        return seen


@dataclass
class Attempt:
    action: str
    args: dict
    outcome: str  # rejected | did_not_fix | made_worse | resolved | tests_failed | invalid
    detail: str = ""
    approval_id: str | None = None
    verification: dict = field(default_factory=dict)

    def line(self) -> str:
        return f"- {self.action}({self.args}): {self.outcome}. {self.detail}".strip()
