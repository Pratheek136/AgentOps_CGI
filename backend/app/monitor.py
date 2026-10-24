"""Polls the shop's /metrics every 2 s, stores a timeseries and evaluates alert rules."""
from __future__ import annotations

import logging
import threading
import time

import httpx

from . import db
from .config import settings, thresholds
from .events import bus
from .runtime import get_shop_runtime

log = logging.getLogger("rootfix.monitor")

ENDPOINTS = ["/checkout", "/cart", "/products"]


class Monitor:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.health_failures = 0
        self.latest: dict = {}
        self.on_sample: list = []  # callbacks(sample) e.g. alert evaluation

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def reset_state(self) -> None:
        self.health_failures = 0
        self.latest = {}

    def _run(self) -> None:
        while not self._stop.is_set():
            t0 = time.time()
            try:
                sample = self.poll()
                for cb in list(self.on_sample):
                    try:
                        cb(sample)
                    except Exception:  # noqa: BLE001
                        log.exception("sample callback failed")
            except Exception:  # noqa: BLE001
                log.exception("monitor poll failed")
            self._stop.wait(max(0.1, thresholds.poll_interval_s - (time.time() - t0)))

    def poll(self) -> dict:
        ts = time.time()
        runtime = get_shop_runtime()
        healthy, data = False, {}
        try:
            r = httpx.get(f"{settings.shop_url}/metrics", timeout=1.5)
            if r.status_code == 200:
                data = r.json()
                healthy = httpx.get(f"{settings.shop_url}/health", timeout=1.5).status_code == 200
        except httpx.HTTPError:
            pass
        self.health_failures = 0 if healthy else self.health_failures + 1
        memory = data.get("memory_mb") or runtime.memory_mb()
        version = data.get("version", "down")
        eps = data.get("endpoints", {})
        rows = []
        for ep in ENDPOINTS:
            m = eps.get(ep, {})
            rows.append((ts, ep, m.get("requests", 0), m.get("errors", 0), m.get("error_rate", 0.0),
                         m.get("p50_ms", 0.0), m.get("p95_ms", 0.0), None, None, None))
        rows.append((ts, "_service", data.get("total_requests"), data.get("total_errors"), None,
                     None, None, memory, int(healthy), version))
        db.conn().executemany(
            "INSERT INTO metrics (ts, endpoint, requests, errors, error_rate, p50_ms, p95_ms, "
            "memory_mb, healthy, version) VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        pay = db.one("SELECT COUNT(*) AS n, SUM(CASE WHEN error IN ('ConnectionError', 'PaymentError') THEN 1 ELSE 0 END) AS e "
                     "FROM orders WHERE ts >= ?", (ts - 30,))
        sample = {
            "ts": ts, "healthy": healthy,
            "payment": {"checks": pay["n"] or 0, "errors": pay["e"] or 0}, "memory_mb": memory, "version": version,
            "health_failures": self.health_failures,
            "endpoints": {ep: eps.get(ep, {"requests": 0, "errors": 0, "error_rate": 0.0,
                                           "p50_ms": 0.0, "p95_ms": 0.0}) for ep in ENDPOINTS},
        }
        self.latest = sample
        bus.publish("metrics", sample)
        return sample


def series(window_s: int = 300) -> dict:
    """Timeseries for charts: checkout error rate, checkout p95, memory, plus markers."""
    since = time.time() - window_s
    rows = db.query("SELECT ts, endpoint, error_rate, p95_ms, memory_mb, healthy, version "
                    "FROM metrics WHERE ts >= ? ORDER BY ts", (since,))
    by_ts: dict[float, dict] = {}
    for r in rows:
        p = by_ts.setdefault(r["ts"], {"ts": r["ts"]})
        if r["endpoint"] == "_service":
            p["memory_mb"] = r["memory_mb"]
            p["healthy"] = r["healthy"]
            p["version"] = r["version"]
        else:
            key = r["endpoint"].strip("/")
            p[f"{key}_error_rate"] = r["error_rate"]
            p[f"{key}_p95_ms"] = r["p95_ms"]
    markers = db.query("SELECT ts, kind, label FROM markers WHERE ts >= ? ORDER BY ts", (since,))
    return {"points": list(by_ts.values()), "markers": markers,
            "thresholds": {"error_rate": thresholds.error_rate, "p95_ms": thresholds.p95_ms,
                           "memory_mb": thresholds.memory_mb_abs}}


monitor = Monitor()
