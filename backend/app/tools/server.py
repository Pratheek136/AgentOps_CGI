"""The tool server: validate -> gate -> execute -> mask -> scan -> store -> audit.

Every agent tool call goes through `invoke`. The HTTP route /api/tools/{name} calls the same function.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field

from .. import approvals, audit, db, retrieval
from ..deploys import add_marker
from ..security import detect_injection, mask, mask_obj, wrap_untrusted
from . import gate, impl
from .registry import TOOLS, ValidationError, validate

log = logging.getLogger("rootfix.tools")
_lock = threading.Lock()
UI_MAX_CHARS = 4000


@dataclass
class ToolResult:
    id: str
    tool: str
    args: dict
    text: str               # masked output
    wrapped: str            # masked output wrapped as untrusted data for the model
    data: object = None
    flags: list[dict] = field(default_factory=list)
    approval_id: str | None = None

    def ui(self) -> dict:
        return {"id": self.id, "tool": self.tool, "args": mask_obj(self.args), "text": self.text[:UI_MAX_CHARS],
                "truncated": len(self.text) > UI_MAX_CHARS, "flags": self.flags, "approval_id": self.approval_id}


def _next_result_id(incident_id: str | None) -> str:
    """Per-incident ids (tr-1 is the first tool result of every incident) so replays stay deterministic."""
    n = (db.one("SELECT COUNT(*) AS c FROM tool_results WHERE incident_id IS ?", (incident_id,)) or {"c": 0})["c"] + 1
    return f"tr-{n}"


def invoke(name: str, args: dict | None, incident_id: str | None, approval_id: str | None = None,
           actor: str = "agent") -> ToolResult:
    try:
        clean = validate(name, args)
    except ValidationError as exc:
        audit.append(actor, "tool.invalid", incident_id=incident_id, tool=name, args=args or {},
                     result={"error": str(exc)})
        raise
    spec = TOOLS[name]
    if name == "record_decision":
        _check_evidence(clean, incident_id)
    used_approval = gate.check(spec, clean, incident_id, approval_id, actor)  # raises GateError (403)

    t0 = time.time()
    if name == "record_decision":
        text, data = "decision recorded", clean
    elif spec.mutating:
        text, data = impl.MUTATING_IMPLS[name](incident_id, clean)
        add_marker("action", _marker_label(name, clean, data, used_approval), incident_id)
    else:
        text, data = impl.READ_IMPLS[name](incident_id, clean)
    text = mask(text)
    flags = [f.to_dict() for f in detect_injection(text)] if name != "record_decision" else []
    with _lock:
        rid = _next_result_id(incident_id)
        db.execute("INSERT INTO tool_results (id, incident_id, ts, tool, args, output, flagged) VALUES (?,?,?,?,?,?,?)",
                   (rid, incident_id, time.time(), name, db.dumps(mask_obj(clean)), text, int(bool(flags))))
    audit.append(actor, "tool.call", incident_id=incident_id, tool=name, args=clean, approval_id=used_approval,
                 result={"id": rid, "summary": text.splitlines()[0][:200] if text else "",
                         "duration_s": round(time.time() - t0, 2), "flagged_lines": len(flags)})
    if flags:
        audit.append("system", "injection.flagged", incident_id=incident_id, tool=name,
                     result={"result_id": rid, "flags": flags})
    return ToolResult(rid, name, clean, text, wrap_untrusted(rid, name, text, [_f(f) for f in flags]),
                      mask_obj(data), flags, used_approval)


def _f(d: dict):
    from ..security import InjectionFlag
    return InjectionFlag(d["line_no"], d["pattern"], d["excerpt"])


EVIDENCE_RE = re.compile(r"^(tr-\d+|log#\d+|KB:[A-Z]{2}-\d{2})$")


def _check_evidence(decision: dict, incident_id: str | None) -> None:
    """Every cited evidence id must exist: tool results of this incident, log lines seen in them, or KB docs."""
    outputs = db.query("SELECT id, output FROM tool_results WHERE incident_id = ?", (incident_id,))
    ids = {o["id"] for o in outputs}
    seen_text = "\n".join(o["output"] for o in outputs)
    inc = db.one("SELECT sample_logs FROM incidents WHERE id = ?", (incident_id,))
    seen_text += "\n" + (inc["sample_logs"] if inc else "")
    unknown = []
    for h in decision["hypotheses"]:
        for e in h["evidence"]:
            e = e.strip()
            ok = bool(EVIDENCE_RE.match(e)) and (
                e in ids or (e.startswith("log#") and re.search(rf"{re.escape(e)}(?!\d)", seen_text) is not None)
                or (e.startswith("KB:") and retrieval.get(e[3:]) is not None))
            if not ok:
                unknown.append(e)
    if unknown:
        raise ValidationError(f"unknown evidence ids {unknown}. Cite ids returned by tools in this "
                              "incident (tr-N, log#N) or KB ids (KB:RB-01).")


def _marker_label(name: str, args: dict, data: object, approval_id: str | None) -> str:
    what = {"restart_service": "restart", "revert_config": "config revert",
            "rollback_deploy": f"rollback→{args.get('to_tag')}", "apply_patch": "patch"}.get(name, name)
    rec = approvals.get(approval_id) if approval_id else None
    return f"{what} ✓ {rec['approver'].split()[0]}" if rec and rec.get("approver") else what
