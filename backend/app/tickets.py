"""Ticket lifecycle, status history, priority changes and the SLA clock."""
from __future__ import annotations

import logging
import threading
import time

from . import audit, db
from .config import SLA_TABLE
from .events import bus

log = logging.getLogger("rootfix.tickets")

NEW, TRIAGED, INVESTIGATING = "New", "Triaged", "Investigating"
AWAITING, RESOLVING, VERIFYING = "Awaiting approval", "Resolving", "Verifying"
RESOLVED, CLOSED, ESCALATED = "Resolved", "Closed", "Escalated"

LIFECYCLE = [NEW, TRIAGED, INVESTIGATING, AWAITING, RESOLVING, VERIFYING, RESOLVED, CLOSED]
OPEN_STATUSES = {NEW, TRIAGED, INVESTIGATING, AWAITING, RESOLVING, VERIFYING}

ALLOWED: dict[str, set[str]] = {
    NEW: {TRIAGED, ESCALATED},
    TRIAGED: {INVESTIGATING, ESCALATED},
    INVESTIGATING: {AWAITING, RESOLVING, VERIFYING, ESCALATED},
    AWAITING: {RESOLVING, INVESTIGATING, ESCALATED},
    RESOLVING: {VERIFYING, INVESTIGATING, ESCALATED},
    VERIFYING: {RESOLVED, INVESTIGATING, ESCALATED},
    RESOLVED: {CLOSED},
    ESCALATED: {CLOSED},
    CLOSED: set(),
}

# stage indicator mapping for the dashboard
STAGE = {NEW: "ingest", TRIAGED: "decide", INVESTIGATING: "decide", AWAITING: "act",
         RESOLVING: "act", VERIFYING: "act", RESOLVED: "report", CLOSED: "report", ESCALATED: "report"}

_lock = threading.Lock()


class TransitionError(Exception):
    pass


def get(incident_id: str) -> dict | None:
    return db.one("SELECT * FROM incidents WHERE id = ?", (incident_id,))


def set_status(incident_id: str, to: str, actor: str = "system", reason: str = "") -> dict:
    with _lock:
        inc = get(incident_id)
        if inc is None:
            raise TransitionError(f"no incident {incident_id}")
        frm = inc["status"]
        if frm == to:
            return inc
        if to not in ALLOWED.get(frm, set()):
            raise TransitionError(f"{incident_id}: {frm} -> {to} not allowed")
        now = time.time()
        sets = {"status": to}
        if to == INVESTIGATING and not inc["responded_at"]:
            sets["responded_at"] = now
        if to == RESOLVED:
            sets["resolved_at"] = now
        if to == CLOSED:
            sets["closed_at"] = now
        if to == ESCALATED:
            sets["escalated_at"] = now
        db.execute(f"UPDATE incidents SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ?",
                   [*sets.values(), incident_id])
        db.execute("INSERT INTO status_history (incident_id, ts, from_status, to_status, actor, reason) "
                   "VALUES (?,?,?,?,?,?)", (incident_id, now, frm, to, actor, reason))
    audit.append(actor, "status.change", incident_id=incident_id,
                 args={"from": frm, "to": to}, result={"reason": reason})
    log.info("%s: %s -> %s (%s)", incident_id, frm, to, reason)
    bus.publish("ticket", {"incident_id": incident_id, "from": frm, "to": to, "reason": reason,
                           "stage": STAGE[to]})
    return get(incident_id)


def set_priority(incident_id: str, result: dict, actor: str = "system", reason: str = "") -> None:
    inc = get(incident_id)
    old = inc["priority"] if inc else None
    db.execute("UPDATE incidents SET priority = ?, impact = ?, urgency = ?, priority_reason = ? WHERE id = ?",
               (result["priority"], result["impact"], result["urgency"], result["reason"], incident_id))
    db.execute("INSERT INTO priority_history (incident_id, ts, from_priority, to_priority, actor, reason) "
               "VALUES (?,?,?,?,?,?)", (incident_id, time.time(), old, result["priority"], actor,
                                        reason or result["reason"]))
    audit.append(actor, "priority.set" if old is None else "priority.change", incident_id=incident_id,
                 args={"from": old, "to": result["priority"]},
                 result={"impact": result["impact"], "urgency": result["urgency"],
                         "reason": reason or result["reason"]})
    bus.publish("ticket", {"incident_id": incident_id, "priority": result["priority"], "from_priority": old})


def open_incident(service: str | None = None, include_escalated: bool = False) -> dict | None:
    """Latest open incident. With include_escalated, an Escalated (human-owned) incident also counts,
    so a still-firing alert is not re-raised as a new incident until someone closes it."""
    statuses = OPEN_STATUSES | ({ESCALATED} if include_escalated else set())
    q = f"SELECT * FROM incidents WHERE status IN ({','.join('?' * len(statuses))})"
    params: list = list(statuses)
    if service:
        q += " AND service = ?"
        params.append(service)
    return db.one(q + " ORDER BY created_at DESC LIMIT 1", params)


def sla(inc: dict, now: float | None = None) -> dict:
    now = now or time.time()
    p = inc.get("priority") or "P4"
    respond_min, resolve_min = SLA_TABLE[p]
    start = inc["created_at"]
    respond_due = start + respond_min * 60
    resolve_due = start + resolve_min * 60
    end = inc.get("resolved_at") or inc.get("escalated_at") or now
    responded = inc.get("responded_at")
    return {
        "priority": p,
        "respond_target_min": respond_min,
        "resolve_target_min": resolve_min,
        "respond_due": respond_due,
        "resolve_due": resolve_due,
        "responded_at": responded,
        "respond_met": (responded - start) <= respond_min * 60 if responded else None,
        "resolve_met": (inc["resolved_at"] - start) <= resolve_min * 60 if inc.get("resolved_at") else None,
        "elapsed_s": round(end - start, 1),
        "used_fraction": round(min(1.5, (end - start) / (resolve_min * 60)), 3),
        "running": inc["status"] in OPEN_STATUSES,
    }


def view(incident_id: str) -> dict | None:
    inc = get(incident_id)
    if inc is None:
        return None
    for k in ("endpoints", "snapshot", "sample_logs", "kb_matches", "verification", "impact_json", "escalation"):
        inc[k] = db.loads(inc[k], inc[k])
    inc["history"] = db.query("SELECT ts, from_status, to_status, actor, reason FROM status_history "
                              "WHERE incident_id = ? ORDER BY id", (incident_id,))
    inc["priority_history"] = db.query("SELECT * FROM priority_history WHERE incident_id = ? ORDER BY id",
                                       (incident_id,))
    inc["sla"] = sla(inc)
    inc["stage"] = STAGE.get(inc["status"], "ingest")
    return inc
