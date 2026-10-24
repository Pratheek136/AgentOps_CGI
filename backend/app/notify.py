"""Stakeholder updates: in-app feed (+ optional Slack webhook). Numbers come from impact.py."""
from __future__ import annotations

import logging
import time

import httpx

from . import approvals, audit, db, impact, tickets
from .config import settings
from .events import bus

log = logging.getLogger("rootfix.notify")


def post(incident_id: str, stage: str, message: str) -> dict:
    ts = time.time()
    nid = db.execute("INSERT INTO notifications (incident_id, ts, stage, message) VALUES (?,?,?,?)",
                     (incident_id, ts, stage, message))
    audit.append("system", "notification.sent", incident_id=incident_id, args={"stage": stage},
                 result={"message": message})
    evt = {"id": nid, "incident_id": incident_id, "ts": ts, "stage": stage, "message": message}
    bus.publish("notification", evt)
    if settings.slack_webhook_url:
        try:
            httpx.post(settings.slack_webhook_url, json={"text": f"*RootFix* {message}"}, timeout=5)
        except httpx.HTTPError as exc:
            log.warning("slack webhook failed: %s", exc)
    return evt


def on_triaged(incident_id: str) -> None:
    inc = tickets.get(incident_id)
    if not inc or inc["priority"] not in ("P1", "P2"):
        return
    since = time.strftime("%H:%M", time.localtime(inc["first_seen"]))
    what = "Checkout disruption" if "checkout" in (inc["alert_rule"] or "") else "Shop degradation"
    imp = impact.compute(incident_id)
    post(incident_id, "Triaged",
         f"{what} {incident_id} ({inc['priority']}) since {since}: about {imp['affected_share']:.0%} of checkout "
         f"attempts are failing. RootFix is investigating; next update when a fix is ready for approval.")


def on_awaiting(incident_id: str, run=None) -> None:
    pend = approvals.pending(incident_id)
    action = pend[0]["summary"] if pend else "a fix"
    imp = impact.compute(incident_id)
    post(incident_id, "Awaiting approval",
         f"{incident_id}: cause identified. Proposed fix: {action[0].lower() + action[1:]}. Waiting for on-call "
         f"approval. About {impact.inr(imp['rupees_at_risk'])} in orders affected so far.")


def on_resolved(incident_id: str, run=None) -> None:
    imp = impact.freeze(incident_id)
    sla = "SLA met" if imp["sla_resolve_met"] else "SLA missed"
    post(incident_id, "Resolved",
         f"Checkout disruption {incident_id} resolved in {impact.dur(imp['time_to_resolve_s'])}; about "
         f"{impact.inr(imp['rupees_at_risk'])} in orders affected ({imp['failed_checkouts']} failed checkouts); "
         f"{sla} ({imp['priority']} target {imp['sla_resolve_target_min']} min). Postmortem to follow.")


def on_escalated(incident_id: str, run=None) -> None:
    imp = impact.freeze(incident_id)
    inc = tickets.get(incident_id)
    reason = (db.loads(inc["escalation"], {}) or {}).get("reason", "needs human investigation") if inc else ""
    post(incident_id, "Escalated",
         f"{incident_id} escalated to the on-call lead: {reason}. About {impact.inr(imp['rupees_at_risk'])} in "
         f"orders affected so far. No automated changes were made beyond those listed in the ticket. "
         f"Next update in 15 minutes.")


def feed(limit: int = 50) -> list[dict]:
    return db.query("SELECT * FROM notifications ORDER BY id DESC LIMIT ?", (limit,))
