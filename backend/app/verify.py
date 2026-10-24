"""Recovery verification on live metrics, sustained over VERIFY_WINDOW_S."""
from __future__ import annotations

import threading
import time

from . import db
from .alerts import memory_slope_mb_per_min
from .config import settings, thresholds
from .events import bus


def baseline(seconds: int = 20) -> dict:
    """Checkout error rate / p95 just before an action (to detect 'made it worse')."""
    since = time.time() - seconds
    r = db.one("SELECT AVG(error_rate) AS er, AVG(p95_ms) AS p95 FROM metrics WHERE endpoint = '/checkout' AND ts >= ?",
               (since,))
    return {"error_rate": round(r["er"] or 0.0, 4), "p95_ms": round(r["p95"] or 0.0, 1)}


def verify(incident_id: str, memory_incident: bool = False, window_s: int | None = None,
           before: dict | None = None, cancelled: threading.Event | None = None) -> dict:
    window = window_s or settings.effective_verify_window_s
    start = time.time()
    grace = 4  # let the restarted process take traffic
    bus.publish("narration", {"incident_id": incident_id,
                              "text": f"Verifying recovery on live metrics for {window} s…"})
    samples: list[dict] = []
    bad_streak = 0
    early_fail = False
    while time.time() - start < window + grace:
        if cancelled is not None and cancelled.is_set():
            break
        time.sleep(thresholds.poll_interval_s)
        if time.time() - start < grace:
            continue
        svc = db.one("SELECT ts, memory_mb, healthy FROM metrics WHERE endpoint = '_service' ORDER BY ts DESC LIMIT 1")
        chk = db.one("SELECT error_rate, p95_ms, requests FROM metrics WHERE endpoint = '/checkout' ORDER BY ts DESC LIMIT 1")
        if not svc or not chk:
            continue
        s = {"ts": svc["ts"], "error_rate": chk["error_rate"] or 0.0, "p95_ms": chk["p95_ms"] or 0.0,
             "requests": chk["requests"] or 0, "memory_mb": svc["memory_mb"], "healthy": bool(svc["healthy"])}
        samples.append(s)
        bad = (not s["healthy"]) or s["error_rate"] >= thresholds.error_rate
        bad_streak = bad_streak + 1 if bad else 0
        bus.publish("verification", {"incident_id": incident_id, "progress": min(1.0, (time.time() - start - grace) / window),
                                     "sample": s})
        if bad_streak >= 4:  # clearly not fixed: stop early to save time
            early_fail = True
            break
    mem_points = [(s["ts"], s["memory_mb"]) for s in samples if s["memory_mb"]]
    slope = memory_slope_mb_per_min(mem_points)
    er_max = max((s["error_rate"] for s in samples), default=1.0)
    er_avg = sum(s["error_rate"] for s in samples) / len(samples) if samples else 1.0
    p95_max = max((s["p95_ms"] for s in samples), default=0.0)
    checks = {
        "error_rate_below_1pct": bool(samples) and all(s["error_rate"] < thresholds.recovered_error_rate for s in samples[1:]) and er_avg < thresholds.recovered_error_rate,
        "p95_below_threshold": bool(samples) and p95_max < thresholds.p95_ms,
        "healthy": bool(samples) and all(s["healthy"] for s in samples),
    }
    if memory_incident:
        checks["memory_not_rising"] = slope < thresholds.memory_slope_mb_per_min
    recovered = (not early_fail) and all(checks.values())
    worse = False
    if before is not None and samples:
        worse = (er_avg > before["error_rate"] + 0.10) or not checks["healthy"]
    return {
        "recovered": recovered, "worse": worse, "early_fail": early_fail,
        "window_s": window, "samples": len(samples),
        "measured": {"error_rate_max": round(er_max, 4), "error_rate_avg": round(er_avg, 4),
                     "p95_ms_max": round(p95_max, 1), "memory_slope_mb_per_min": round(slope, 1),
                     "memory_mb_last": mem_points[-1][1] if mem_points else None},
        "before": before, "checks": checks, "finished_at": time.time(),
    }
