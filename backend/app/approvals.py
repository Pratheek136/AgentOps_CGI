"""Approval requests for gated actions: create, decide (named approver + role), wait."""
from __future__ import annotations

import json
import threading
import time

from . import audit, db
from .config import ON_CALL_ROLES, find_user
from .events import bus

_events: dict[str, threading.Event] = {}
_lock = threading.Lock()

PENDING, APPROVED, REJECTED, EXPIRED = "pending", "approved", "rejected", "expired"


class ApprovalError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def canonical_args(args: dict) -> str:
    return json.dumps(args, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def create(incident_id: str, tool: str, args: dict, *, diff_preview: str, risk: str, evidence: list[str],
           hypothesis: str, confidence: float, expected_effect: str, rollback_plan: str, summary: str) -> dict:
    with _lock:
        n = (db.one("SELECT COUNT(*) AS c FROM approvals") or {"c": 0})["c"] + 1
        apr_id = f"APR-{n:04d}"
        db.execute(
            "INSERT INTO approvals (id, incident_id, created_at, status, tool, args, diff_preview, risk, evidence, "
            "hypothesis, confidence, expected_effect, rollback_plan, summary) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (apr_id, incident_id, time.time(), PENDING, tool, canonical_args(args), diff_preview, risk,
             db.dumps(evidence), hypothesis, confidence, expected_effect, rollback_plan, summary))
        _events[apr_id] = threading.Event()
    audit.append("agent", "approval.requested", incident_id=incident_id, tool=tool, args=args,
                 evidence=evidence, approval_id=apr_id, result={"summary": summary, "risk": risk})
    rec = get(apr_id)
    bus.publish("approval", rec)
    return rec


def get(apr_id: str) -> dict | None:
    r = db.one("SELECT * FROM approvals WHERE id = ?", (apr_id,))
    if r:
        r["args"] = json.loads(r["args"])
        r["evidence"] = db.loads(r["evidence"], [])
    return r


def pending(incident_id: str | None = None) -> list[dict]:
    q, params = "SELECT id FROM approvals WHERE status = ?", [PENDING]
    if incident_id:
        q += " AND incident_id = ?"
        params.append(incident_id)
    return [get(r["id"]) for r in db.query(q + " ORDER BY created_at", params)]


def for_incident(incident_id: str) -> list[dict]:
    return [get(r["id"]) for r in db.query("SELECT id FROM approvals WHERE incident_id = ? ORDER BY created_at",
                                           (incident_id,))]


def decide(apr_id: str, approver: str, approve: bool, reason: str) -> dict:
    rec = get(apr_id)
    if rec is None:
        raise ApprovalError("no such approval", 404)
    if rec["status"] != PENDING:
        raise ApprovalError(f"approval already {rec['status']}", 409)
    if not reason or not reason.strip():
        raise ApprovalError("a reason is required", 422)
    user = find_user(approver)
    if user is None:
        raise ApprovalError(f"unknown user {approver!r}", 403)
    if not user.can_approve:
        audit.append(approver, "approval.denied_role", incident_id=rec["incident_id"], tool=rec["tool"],
                     approval_id=apr_id, result={"role": user.role})
        raise ApprovalError(f"{approver} ({user.role}) cannot approve changes", 403)
    inc = db.one("SELECT priority FROM incidents WHERE id = ?", (rec["incident_id"],))
    if inc and inc["priority"] == "P1" and user.role not in ON_CALL_ROLES:
        raise ApprovalError("P1 changes require the on-call role", 403)
    status = APPROVED if approve else REJECTED
    db.execute("UPDATE approvals SET status = ?, approver = ?, reason = ?, decided_at = ? WHERE id = ?",
               (status, approver, reason.strip(), time.time(), apr_id))
    audit.append(approver, f"approval.{status}", incident_id=rec["incident_id"], tool=rec["tool"],
                 args=rec["args"], approval_id=apr_id, result={"reason": reason.strip(), "role": user.role})
    out = get(apr_id)
    bus.publish("approval", out)
    ev = _events.get(apr_id)
    if ev:
        ev.set()
    return out


def expire(apr_id: str, reason: str = "no decision within APPROVAL_TIMEOUT_S") -> None:
    db.execute("UPDATE approvals SET status = ?, reason = ?, decided_at = ? WHERE id = ? AND status = ?",
               (EXPIRED, reason, time.time(), apr_id, PENDING))
    rec = get(apr_id)
    audit.append("system", "approval.expired", incident_id=rec["incident_id"], tool=rec["tool"],
                 approval_id=apr_id, result={"reason": reason})
    bus.publish("approval", rec)


def wait(apr_id: str, timeout_s: float, cancelled: threading.Event | None = None) -> dict:
    ev = _events.setdefault(apr_id, threading.Event())
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if ev.wait(timeout=0.5):
            break
        if cancelled is not None and cancelled.is_set():
            break
        if get(apr_id)["status"] != PENDING:  # decided by another process/thread
            break
    rec = get(apr_id)
    if rec["status"] == PENDING and not (cancelled and cancelled.is_set()):
        expire(apr_id)
        rec = get(apr_id)
    return rec


def consume(apr_id: str) -> None:
    db.execute("UPDATE approvals SET consumed = 1, executed_at = ? WHERE id = ?", (time.time(), apr_id))
