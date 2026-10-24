"""Deterministic ITIL priority: impact x urgency -> P1..P4. Never decided by the LLM."""
from __future__ import annotations

from dataclasses import dataclass

from .config import SLA_TABLE

RANK = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}


@dataclass
class Signals:
    revenue_error_rate: float = 0.0     # checkout/payment path error rate (0-1)
    service_down: bool = False
    revenue_latency_breach: bool = False
    revenue_path_affected: bool = False
    worsening: bool = False


@dataclass
class PriorityResult:
    impact: str
    urgency: str
    priority: str
    reason: str
    respond_min: int
    resolve_min: int

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def impact_of(s: Signals) -> tuple[str, str]:
    if s.service_down:
        return "High", "service is down"
    if s.revenue_error_rate >= 0.20:
        return "High", f"checkout error rate {s.revenue_error_rate:.0%} ≥ 20%"
    if s.revenue_error_rate >= 0.05:
        return "Medium", f"checkout error rate {s.revenue_error_rate:.0%} (5-20%)"
    if s.revenue_latency_breach:
        return "Medium", "latency breach on the revenue path"
    return "Low", "no revenue-path errors"


def urgency_of(s: Signals) -> tuple[str, str]:
    if s.revenue_path_affected:
        return "High", "revenue path affected"
    if s.worsening:
        return "High", "signal is worsening"
    return "Medium", "stable, non-revenue signal"


def matrix(impact: str, urgency: str) -> str:
    if impact == "High" and urgency == "High":
        return "P1"
    if (impact, urgency) in {("High", "Medium"), ("Medium", "High")}:
        return "P2"
    if impact == "Medium" and urgency == "Medium":
        return "P3"
    return "P4"


def compute(s: Signals) -> PriorityResult:
    impact, ir = impact_of(s)
    urgency, ur = urgency_of(s)
    p = matrix(impact, urgency)
    respond, resolve = SLA_TABLE[p]
    return PriorityResult(impact, urgency, p, f"Impact {impact} ({ir}); urgency {urgency} ({ur})",
                          respond, resolve)


def is_higher(new: str, old: str | None) -> bool:
    return old is None or RANK[new] < RANK[old]
