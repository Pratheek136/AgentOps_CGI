"""Alert rules evaluated on every monitor sample, plus periodic priority re-evaluation."""
from __future__ import annotations

import logging
import time
from collections import deque

from . import ingest, priority, tickets
from .config import settings, thresholds

log = logging.getLogger("rootfix.alerts")

MIN_REQUESTS = 5


def memory_slope_mb_per_min(points: list[tuple[float, float]]) -> float:
    """Least-squares slope of (ts, MB) in MB/min."""
    if len(points) < 5:
        return 0.0
    n = len(points)
    mx = sum(t for t, _ in points) / n
    my = sum(m for _, m in points) / n
    den = sum((t - mx) ** 2 for t, _ in points)
    if den == 0:
        return 0.0
    return sum((t - mx) * (m - my) for t, m in points) / den * 60


class AlertEngine:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.breach_since: dict[str, float | None] = {}
        self.memory: deque[tuple[float, float]] = deque(maxlen=200)
        self.last_reeval = 0.0

    @property
    def sustain(self) -> dict[str, float]:
        demo = settings.demo_mode
        return {
            "checkout_error_rate": 10 if demo else thresholds.error_rate_for_s,
            "checkout_p95_latency": 15 if demo else thresholds.p95_for_s,
            "memory_growth": 20 if demo else thresholds.memory_rising_for_s,
        }

    def current_signals(self, sample: dict, slope: float) -> priority.Signals:
        c = sample["endpoints"].get("/checkout", {})
        rate = c.get("error_rate", 0.0) if c.get("requests", 0) >= MIN_REQUESTS else 0.0
        return priority.Signals(
            revenue_error_rate=rate,
            service_down=sample["health_failures"] >= thresholds.health_failures,
            revenue_latency_breach=c.get("p95_ms", 0.0) > thresholds.p95_ms,
            revenue_path_affected=rate >= thresholds.error_rate or c.get("p95_ms", 0.0) > thresholds.p95_ms,
            worsening=slope > thresholds.memory_slope_mb_per_min,
        )

    def _held(self, rule: str, breached: bool, now: float) -> float | None:
        """Returns breach start time once the breach has lasted the sustain period."""
        if not breached:
            self.breach_since[rule] = None
            return None
        start = self.breach_since.get(rule) or now
        self.breach_since[rule] = start
        return start if now - start >= self.sustain.get(rule, 0) else None

    def on_sample(self, sample: dict) -> None:
        now = sample["ts"]
        if sample.get("memory_mb"):
            self.memory.append((now, sample["memory_mb"]))
        recent = [p for p in self.memory if p[0] >= now - 60]
        slope = memory_slope_mb_per_min(recent)
        sig = self.current_signals(sample, slope)
        c = sample["endpoints"].get("/checkout", {})
        enough = c.get("requests", 0) >= MIN_REQUESTS

        candidates: list[ingest.Alert] = []
        if sample["health_failures"] >= thresholds.health_failures:
            candidates.append(ingest.Alert("health_check_failing",
                                           f"Shop /health failing {sample['health_failures']} times in a row",
                                           now - sample["health_failures"] * thresholds.poll_interval_s,
                                           values={"health_failures": sample["health_failures"]}, signals=sig))
        start = self._held("checkout_error_rate", enough and c.get("error_rate", 0) > thresholds.error_rate, now)
        if start:
            candidates.append(ingest.Alert(
                "checkout_error_rate",
                f"Checkout failing for {c['error_rate']:.0%} of customers (threshold {thresholds.error_rate:.0%})",
                start, values={"error_rate": c["error_rate"], "p95_ms": c.get("p95_ms")}, signals=sig))
        start = self._held("checkout_p95_latency", enough and c.get("p95_ms", 0) > thresholds.p95_ms, now)
        if start:
            candidates.append(ingest.Alert(
                "checkout_p95_latency",
                f"Checkout p95 latency {c['p95_ms']:.0f} ms (threshold {thresholds.p95_ms:.0f} ms)",
                start, values={"p95_ms": c["p95_ms"]}, signals=sig))
        mem_bad = (sample.get("memory_mb") or 0) > thresholds.memory_mb_abs or (
            len(recent) >= 10 and slope > thresholds.memory_slope_mb_per_min)
        start = self._held("memory_growth", mem_bad, now)
        if start:
            candidates.append(ingest.Alert(
                "memory_growth",
                f"Shop memory rising {slope:.0f} MB/min (now {sample['memory_mb']:.0f} MB)",
                start, endpoints=["/checkout", "/products"],
                values={"memory_mb": sample["memory_mb"], "slope_mb_per_min": round(slope, 1)}, signals=sig))

        if candidates and not tickets.open_incident(candidates[0].service, include_escalated=True):
            ingest.create_incident(candidates[0])

        if now - self.last_reeval >= 30:
            self.last_reeval = now
            self._reevaluate(sig)

    def _reevaluate(self, sig: priority.Signals) -> None:
        inc = tickets.open_incident()
        if not inc or not inc["priority"]:
            return
        res = priority.compute(sig)
        if priority.is_higher(res.priority, inc["priority"]):
            tickets.set_priority(inc["id"], res.to_dict(), reason=f"auto-escalated: {res.reason}")
        # decreases are never automatic: a human must lower priority


engine = AlertEngine()
