"""Deterministic business impact from ground truth (orders + metrics). Synthetic demo data."""
from __future__ import annotations

import time

from . import db, tickets
from .config import SLA_TABLE, thresholds

LABEL = "synthetic demo data"


def window(inc: dict, now: float | None = None) -> tuple[float, float, bool]:
    """(start, end, final): first bad signal -> verified recovery (or escalation / now)."""
    end = inc.get("resolved_at") or inc.get("escalated_at")
    return inc["first_seen"], end or (now or time.time()), end is not None


def compute(incident_id: str, now: float | None = None) -> dict:
    inc = tickets.get(incident_id)
    if inc is None:
        return {}
    start, end, final = window(inc, now)
    o = db.one("SELECT COUNT(*) AS attempts, SUM(CASE WHEN ok = 0 THEN 1 ELSE 0 END) AS failed, "
               "COALESCE(SUM(CASE WHEN ok = 0 THEN value_inr END), 0) AS rupees "
               "FROM orders WHERE ts >= ? AND ts <= ?", (start, end))
    peak = db.one("SELECT MAX(error_rate) AS m FROM metrics WHERE endpoint = '/checkout' AND ts >= ? AND ts <= ?",
                  (start, end))
    apr = db.query("SELECT status FROM approvals WHERE incident_id = ?", (incident_id,))
    p = inc["priority"] or "P4"
    respond_min, resolve_min = SLA_TABLE[p]
    responded, resolved = inc.get("responded_at"), inc.get("resolved_at")
    attempts, failed = o["attempts"] or 0, o["failed"] or 0
    ttr_s = round(resolved - inc["created_at"], 1) if resolved else None
    return {
        "incident_id": incident_id,
        "label": LABEL,
        "final": final,
        "window_start": start,
        "window_end": end,
        "disruption_minutes": round((end - start) / 60, 1),
        "checkout_attempts": attempts,
        "failed_checkouts": failed,
        "affected_share": round(failed / attempts, 4) if attempts else 0.0,
        "rupees_at_risk": round(float(o["rupees"] or 0), 2),
        "peak_error_rate": round(peak["m"] or 0.0, 4),
        "priority": p,
        "time_to_respond_s": round(responded - inc["created_at"], 1) if responded else None,
        "time_to_resolve_s": ttr_s,
        "time_to_detect_s": round(inc["created_at"] - start, 1),
        "sla_respond_target_min": respond_min,
        "sla_resolve_target_min": resolve_min,
        "sla_respond_met": (responded - inc["created_at"]) <= respond_min * 60 if responded else None,
        "sla_resolve_met": ttr_s <= resolve_min * 60 if ttr_s is not None else None,
        "escalated": inc["status"] == tickets.ESCALATED or bool(inc.get("escalated_at")),
        "approvals_requested": len(apr),
        "approvals_given": sum(a["status"] == "approved" for a in apr),
        "approvals_rejected": sum(a["status"] == "rejected" for a in apr),
        "error_threshold": thresholds.error_rate,
    }


def freeze(incident_id: str) -> dict:
    data = compute(incident_id)
    db.execute("UPDATE incidents SET impact_json = ? WHERE id = ?", (db.dumps(data), incident_id))
    return data


def inr(v: float) -> str:
    """₹ with Indian digit grouping, no decimals (e.g. ₹1,23,456)."""
    n = int(round(v))
    s = str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups) + "," + tail
    return f"{'-' if n < 0 else ''}₹{s}"


def dur(seconds: float | None) -> str:
    if seconds is None:
        return "n/a"
    s = int(round(seconds))
    return f"{s // 60}m {s % 60:02d}s" if s >= 60 else f"{s}s"
