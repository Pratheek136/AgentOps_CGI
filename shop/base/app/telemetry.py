"""Rolling-window request metrics + structured JSON logging."""
import json
import os
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

WINDOW_S = 30


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[str, deque] = defaultdict(deque)  # endpoint -> (ts, ok, latency_ms)
        self.total_requests = 0
        self.total_errors = 0

    def record(self, endpoint: str, status: int, latency_ms: float) -> None:
        now = time.time()
        with self._lock:
            self._events[endpoint].append((now, status < 500, latency_ms))
            self.total_requests += 1
            self.total_errors += status >= 500
            self._trim(now)

    def _trim(self, now: float) -> None:
        for dq in self._events.values():
            while dq and dq[0][0] < now - WINDOW_S:
                dq.popleft()

    def snapshot(self) -> dict:
        now = time.time()
        out = {}
        with self._lock:
            self._trim(now)
            for ep, dq in self._events.items():
                n = len(dq)
                errs = sum(1 for _, ok, _ in dq if not ok)
                lats = sorted(l for _, _, l in dq)
                out[ep] = {
                    "requests": n,
                    "errors": errs,
                    "error_rate": round(errs / n, 4) if n else 0.0,
                    "p50_ms": round(_pct(lats, 50), 1),
                    "p95_ms": round(_pct(lats, 95), 1),
                }
        return out


def _pct(values: list[float], p: int) -> float:
    if not values:
        return 0.0
    k = max(0, min(len(values) - 1, int(round(p / 100 * len(values) + 0.5)) - 1))
    return values[k]


class JsonLogger:
    def __init__(self) -> None:
        path = os.getenv("SHOP_LOG_PATH")
        self._path = Path(path) if path else None
        self._lock = threading.Lock()
        if self._path:
            self._path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, level: str, message: str, **fields) -> None:
        rec = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
               "level": level, "message": message, **fields}
        line = json.dumps(rec, default=str)
        if self._path is None:
            print(line, flush=True)
            return
        with self._lock, open(self._path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
