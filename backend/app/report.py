"""Markdown postmortem from a Jinja template. Facts from the DB; the LLM writes prose only."""
from __future__ import annotations

import json
import logging
import re
import time

from jinja2 import Environment, FileSystemLoader

from . import approvals, audit, db, impact, tickets
from .config import paths
from .events import bus
from .security import mask

log = logging.getLogger("rootfix.report")

_env = Environment(loader=FileSystemLoader(str(paths.root / "backend" / "app" / "templates")),
                   trim_blocks=False, lstrip_blocks=False, autoescape=False)

NUMERIC_CLAIM = re.compile(r"(₹|\bRs\.?\b|\bINR\b|\d[\d,.]*\s*(%|percent|mins?\b|minutes?|seconds?|secs?\b|hours?|"
                           r"orders?|customers?|checkouts?|ms\b|requests?))", re.I)

PROSE_PROMPT = """Write the narrative parts of a short incident postmortem for business and engineering readers.
Use ONLY the facts below. Do NOT include any numbers for money, percentages, durations or counts (the report
fills those in from computed data); deploy tags and config key names are fine.
Return ONLY a JSON object: {"summary": "2-3 sentences", "root_cause": "2-4 sentences", "follow_ups": ["3 short items"]}

FACTS:
"""


def strip_numeric_claims(text: str) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(s for s in sentences if not NUMERIC_CLAIM.search(s)).strip()


def _fallback_prose(inc: dict, decision: dict | None, resolved: bool) -> dict:
    cause = decision["hypotheses"][0]["cause"] if decision else "not determined"
    fix = {"revert_config": "config revert", "rollback_deploy": "rollback to the last good deploy",
           "apply_patch": "code patch", "restart_service": "restart"}.get((decision or {}).get("chosen_action"), "fix")
    return {
        "summary": (f"{inc['signal']}. RootFix identified the most likely cause and, after human approval, "
                    f"applied a {fix}; recovery was verified on live metrics.") if resolved else
                   f"{inc['signal']}. RootFix investigated and escalated to the on-call lead.",
        "root_cause": f"Most likely cause: {cause}.",
        "follow_ups": ["Add a pre-deploy check that would have caught this change.",
                       "Review the runbook used and update it with this incident.",
                       "Confirm alert thresholds gave early enough warning."],
    }


def _llm_prose(run, facts: dict) -> dict | None:
    if run is None or run.provider is None:
        return None
    try:
        resp = run.provider.chat("You write concise, factual incident postmortems.",
                                 [{"role": "user", "content": PROSE_PROMPT + json.dumps(facts, default=str)}], [])
        m = re.search(r"\{.*\}", resp.text, re.S)
        data = json.loads(m.group(0)) if m else None
        if not data:
            return None
        return {
            "summary": strip_numeric_claims(mask(str(data.get("summary", "")))),
            "root_cause": strip_numeric_claims(mask(str(data.get("root_cause", "")))),
            "follow_ups": [strip_numeric_claims(mask(str(f))) for f in data.get("follow_ups", [])][:5],
        }
    except Exception as exc:  # noqa: BLE001
        log.warning("LLM prose failed, using template prose: %s", exc)
        return None


TIMELINE_ACTIONS = {
    "incident.created": lambda r: f"Incident opened: {(r['args'] or {}).get('signal', '')}",
    "priority.set": lambda r: f"Priority set to {(r['args'] or {}).get('to')} (deterministic rules)",
    "priority.change": lambda r: f"Priority changed {(r['args'] or {}).get('from')} → {(r['args'] or {}).get('to')}",
    "status.change": lambda r: f"Status → {(r['args'] or {}).get('to')}",
    "decision.recorded": lambda r: f"Decision recorded: {(r['args'] or {}).get('chosen_action')}",
    "approval.requested": lambda r: f"Approval requested ({r['approval_id']}): {(r['result'] or {}).get('summary', '')}",
    "approval.approved": lambda r: f"Approved ({r['approval_id']}): “{(r['result'] or {}).get('reason', '')}”",
    "approval.rejected": lambda r: f"Rejected ({r['approval_id']}): “{(r['result'] or {}).get('reason', '')}”",
    "verification": lambda r: f"Verification: {'recovered' if (r['result'] or {}).get('recovered') else 'not recovered'}",
    "auto_rollback": lambda r: f"Automatic rollback to {(r['args'] or {}).get('to')}",
    "injection.flagged": lambda r: "⚠ Untrusted instruction found in tool output; ignored",
    "tool.rejected": lambda r: f"Tool call blocked by the approval gate: {r['tool']}",
}
MUTATING = {"revert_config", "rollback_deploy", "apply_patch", "restart_service"}


def _timeline(incident_id: str) -> list[dict]:
    out = []
    for r in reversed(audit.entries(incident_id, 1000)):
        if r["action"] in TIMELINE_ACTIONS:
            out.append({"ts": r["ts"], "actor": r["actor"], "text": TIMELINE_ACTIONS[r["action"]](r).replace("|", "/")})
        elif r["action"] == "tool.call" and r["tool"] in MUTATING:
            out.append({"ts": r["ts"], "actor": r["actor"], "text": f"Executed {r['tool']}: {(r['result'] or {}).get('summary', '')}"[:160].replace("|", "/")})
    return out


def generate(incident_id: str, run=None) -> str:
    inc = tickets.view(incident_id)
    imp = impact.freeze(incident_id)
    traces = db.query("SELECT kind, summary, data FROM trace WHERE incident_id = ? ORDER BY id", (incident_id,))
    decisions = [db.loads(t["data"]) for t in traces if t["kind"] == "decision"]
    decision = decisions[-1] if decisions else None
    failed = [t["summary"] for t in traces if t["kind"] in ("rejected", "not_fixed", "auto_rollback")]
    resolved = inc["status"] in (tickets.RESOLVED, tickets.CLOSED) and bool(inc["resolved_at"])
    facts = {"incident": inc["id"], "signal": inc["signal"], "service": inc["service"], "status": inc["status"],
             "bad_deploy": inc["deploy_tag"], "last_good_deploy": inc["prev_tag"],
             "decision": decision, "what_did_not_work": failed, "escalation": inc.get("escalation")}
    prose = _llm_prose(run, facts)
    author = f"the AI agent ({run.provider.model})" if prose and prose.get("summary") else "RootFix templates (no LLM)"
    if not prose or not prose.get("summary"):
        prose = _fallback_prose(inc, decision, resolved)
    title = ("Checkout outage" if imp["peak_error_rate"] >= 0.5 else "Checkout degradation") if "checkout" in (inc["alert_rule"] or "") \
        else "Shop degradation"
    md = _env.get_template("postmortem.md.j2").render(
        inc=inc, imp=imp, title=title, prose=prose, timeline=_timeline(incident_id),
        evidence=(decision or {}).get("hypotheses", [{}])[0].get("evidence", []) if decision else [],
        hypotheses=(decision or {}).get("hypotheses", []), actions=approvals.for_incident(incident_id),
        ver=inc.get("verification"), failed=failed, escalation=inc.get("escalation"),
        chain=audit.verify_chain(), now=time.time(),
        author=author,
        t=lambda ts: time.strftime("%H:%M:%S", time.localtime(ts)) if ts else "n/a",
        pct=lambda v: f"{(v or 0) * 100:.1f}%", inr=impact.inr, dur=impact.dur,
        met=lambda v: "met ✓" if v else ("missed ✗" if v is False else "n/a"),
    )
    md = mask(md)
    db.execute("UPDATE incidents SET report_md = ? WHERE id = ?", (md, incident_id))
    audit.append("system", "report.generated", incident_id=incident_id,
                 result={"chars": len(md), "rupees_at_risk": imp["rupees_at_risk"], "sla_met": imp["sla_resolve_met"]})
    bus.publish("report", {"incident_id": incident_id})
    outcome = "SLA met" if imp["sla_resolve_met"] else ("escalated" if imp["escalated"] else "SLA missed")
    bus.publish("narration", {"incident_id": incident_id, "text": f"Postmortem ready: {impact.inr(imp['rupees_at_risk'])} "
                              f"in orders affected, {outcome}. See the Outcome report tab."})
    return md
