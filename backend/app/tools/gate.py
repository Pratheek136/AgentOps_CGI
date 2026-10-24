"""Approval enforcement for mutating tools. Enforced in code, whatever the model says."""
from __future__ import annotations

from .. import approvals, audit, db
from .registry import GATED, LOW, READ, ToolSpec


class GateError(Exception):
    status = 403


def needs_approval(spec: ToolSpec, incident_id: str | None) -> bool:
    if spec.tier == GATED:
        return True
    if spec.tier == LOW:
        inc = db.one("SELECT priority FROM incidents WHERE id = ?", (incident_id,)) if incident_id else None
        return inc is None or inc["priority"] in ("P1", "P2")
    return False


def check(spec: ToolSpec, args: dict, incident_id: str | None, approval_id: str | None, actor: str) -> str | None:
    """Raises GateError (and audits it) unless the call is allowed. Returns the approval id used, if any."""
    if spec.tier == READ or not needs_approval(spec, incident_id):
        return None
    reason = None
    rec = approvals.get(approval_id) if approval_id else None
    if rec is None:
        reason = "no approval record"
    elif rec["status"] != approvals.APPROVED:
        reason = f"approval {approval_id} is {rec['status']}"
    elif rec["consumed"]:
        reason = f"approval {approval_id} was already used"
    elif rec["tool"] != spec.name:
        reason = f"approval {approval_id} is for {rec['tool']}, not {spec.name}"
    elif rec["incident_id"] != incident_id:
        reason = f"approval {approval_id} belongs to another incident"
    elif approvals.canonical_args(rec["args"]) != approvals.canonical_args(args):
        reason = f"arguments differ from what was approved in {approval_id}"
    if reason:
        audit.append(actor, "tool.rejected", incident_id=incident_id, tool=spec.name, args=args,
                     approval_id=approval_id, result={"status": 403, "reason": reason})
        raise GateError(f"403 Forbidden: {spec.name} requires an approved approval record ({reason})")
    approvals.consume(approval_id)
    return approval_id
