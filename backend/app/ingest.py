"""Alert -> Incident record: service, endpoints, signals snapshot, logs, deploys, KB matches."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from . import audit, db, gitinfo, logsource, priority, retrieval, tickets
from .events import bus
from .security import detect_injection, mask

log = logging.getLogger("rootfix.ingest")

_lock = threading.Lock()
on_triaged: list[Callable[[str], None]] = []


@dataclass
class Alert:
    rule: str
    signal: str
    first_seen: float
    service: str = "shop"
    endpoints: list[str] = field(default_factory=lambda: ["/checkout"])
    values: dict = field(default_factory=dict)
    signals: priority.Signals = field(default_factory=priority.Signals)


def _snapshot(since: float) -> list[dict]:
    rows = db.query("SELECT ts, endpoint, error_rate, p95_ms, memory_mb, healthy FROM metrics "
                    "WHERE ts >= ? AND endpoint IN ('/checkout', '_service') ORDER BY ts", (since,))
    points: dict[float, dict] = {}
    for r in rows:
        p = points.setdefault(r["ts"], {"ts": round(r["ts"], 1)})
        if r["endpoint"] == "_service":
            p["memory_mb"], p["healthy"] = r["memory_mb"], r["healthy"]
        else:
            p["error_rate"], p["p95_ms"] = r["error_rate"], r["p95_ms"]
    return list(points.values())


def _sample_logs() -> tuple[list[dict], list[dict]]:
    recs = logsource.read(since_s=120, level="ERROR", limit=5)
    lines, flags = [], []
    for r in recs:
        text = mask(logsource.format_record(r, with_traceback=True))
        f = detect_injection(text)
        lines.append({"line": r["line"], "text": text, "flagged": bool(f)})
        flags += [x.to_dict() for x in f]
    return lines, flags


def create_incident(alert: Alert) -> dict | None:
    with _lock:
        existing = tickets.open_incident(alert.service, include_escalated=True)
        if existing:
            audit.append("system", "alert.deduplicated", incident_id=existing["id"],
                         args={"rule": alert.rule}, result={"signal": alert.signal})
            return None
        seq = (db.one("SELECT MAX(seq) AS m FROM incidents") or {}).get("m") or 0
        inc_id = f"INC-{seq + 1:04d}"
        now = time.time()
        deploy = gitinfo.current_deploy()
        sample, flags = _sample_logs()
        error_text = " ".join(s["text"].split("\n")[0] for s in sample[:3])
        kb = retrieval.search(f"{alert.signal} {alert.rule} {error_text}", k=3)
        db.execute(
            "INSERT INTO incidents (id, seq, service, endpoints, alert_rule, signal, first_seen, created_at, "
            "status, snapshot, sample_logs, deploy_tag, deploy_sha, prev_tag, kb_matches) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (inc_id, seq + 1, alert.service, db.dumps(alert.endpoints), alert.rule, alert.signal,
             alert.first_seen, now, tickets.NEW, db.dumps(_snapshot(now - 120)), db.dumps(sample),
             deploy["tag"], deploy["sha"], deploy["prev_tag"],
             db.dumps([{k: m[k] for k in ("id", "title", "score")} for m in kb])),
        )
        db.execute("INSERT INTO status_history (incident_id, ts, from_status, to_status, actor, reason) "
                   "VALUES (?,?,?,?,?,?)", (inc_id, now, None, tickets.NEW, "system", alert.signal))
    audit.append("system", "incident.created", incident_id=inc_id,
                 args={"rule": alert.rule, "signal": alert.signal, "values": alert.values},
                 result={"deploy": deploy, "kb": [m["id"] for m in kb]})
    if flags:
        audit.append("system", "injection.flagged", incident_id=inc_id, args={"source": "sample_logs"},
                     result={"flags": flags})
    log.info("created %s: %s", inc_id, alert.signal)
    bus.publish("incident", {"incident_id": inc_id, "created": True, "signal": alert.signal})
    bus.publish("narration", {"incident_id": inc_id, "text": f"Alert: {alert.signal}. Opening {inc_id}."})

    result = priority.compute(alert.signals)
    tickets.set_priority(inc_id, result.to_dict())
    tickets.set_status(inc_id, tickets.TRIAGED, reason=f"{result.priority}: {result.reason}")
    for cb in list(on_triaged):
        threading.Thread(target=_safe, args=(cb, inc_id), daemon=True).start()
    return tickets.view(inc_id)


def _safe(cb: Callable[[str], None], inc_id: str) -> None:
    try:
        cb(inc_id)
    except Exception:  # noqa: BLE001
        log.exception("on_triaged callback failed for %s", inc_id)
