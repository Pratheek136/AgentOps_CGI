"""Agent loop: investigate -> decide -> request approval -> act -> verify -> re-plan / escalate."""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from .. import approvals, audit, db, gitinfo, tickets
from .. import verify as verifier
from ..config import llm_config, settings
from ..events import bus
from ..security import mask
from ..tools import impl
from ..tools import server as tool_server
from ..tools.gate import GateError, needs_approval
from ..tools.registry import ACTION_TOOLS, TOOLS, ValidationError, validate
from .prompts import MEMORY_RESTART_FIRST_POLICY, SYSTEM_PROMPT, briefing
from .providers import LLMResponse, ProviderError, ToolCall, make_provider
from .schemas import Attempt, Decision

log = logging.getLogger("rootfix.agent")

# lifecycle hooks (notifications, reports) registered by other modules: name -> [fn(incident_id, run)]
hooks: dict[str, list[Callable[[str, "AgentRun"], None]]] = {"awaiting": [], "resolved": [], "escalated": []}

_runs: dict[str, "AgentRun"] = {}
_runs_lock = threading.Lock()

ACTION_WORDS = {
    "revert_config": "config revert", "rollback_deploy": "rollback", "apply_patch": "code patch",
    "restart_service": "restart",
}


def start(incident_id: str, scenario: str | None = None, provider: str | None = None) -> None:
    with _runs_lock:
        if incident_id in _runs:
            return
        run = AgentRun(incident_id, scenario or "live", provider)
        _runs[incident_id] = run
    threading.Thread(target=run.run, name=f"agent-{incident_id}", daemon=True).start()


def cancel_all() -> None:
    with _runs_lock:
        for r in _runs.values():
            r.cancelled.set()
        _runs.clear()


def trace(incident_id: str, kind: str, summary: str, data: object = None) -> dict:
    ts = time.time()
    rid = db.execute("INSERT INTO trace (incident_id, ts, kind, summary, data) VALUES (?,?,?,?,?)",
                     (incident_id, ts, kind, summary, db.dumps(data)))
    evt = {"id": rid, "incident_id": incident_id, "ts": ts, "kind": kind, "summary": summary, "data": data}
    bus.publish("trace", evt)
    return evt


def narrate(incident_id: str, text: str) -> None:
    bus.publish("narration", {"incident_id": incident_id, "text": text})


def _fire(name: str, incident_id: str, run: "AgentRun | None" = None) -> None:
    for fn in hooks.get(name, []):
        try:
            fn(incident_id, run)
        except Exception:  # noqa: BLE001
            log.exception("hook %s failed", name)


class Escalate(Exception):
    pass


class AgentRun:
    def __init__(self, incident_id: str, scenario: str, provider_name: str | None = None) -> None:
        self.incident_id = incident_id
        self.scenario = scenario
        self.provider_name = provider_name
        self.cancelled = threading.Event()
        self.messages: list[dict] = []
        self.tried: list[Attempt] = []
        self.decision: Decision | None = None
        self.decision_used = True
        self.steps = 0
        self.gated_actions = 0
        self.patches = 0
        self.patch_test_failures = 0
        self.nudges = 0
        self.started = time.time()
        self.done = False
        self.provider = None
        inc = tickets.get(incident_id)
        self.memory_incident = bool(inc and inc["alert_rule"] == "memory_growth")

    # ------------------------------------------------------------ main loop
    def run(self) -> None:
        try:
            self._run()
        except Escalate as exc:
            self._escalate(str(exc))
        except Exception as exc:  # noqa: BLE001
            log.exception("agent crashed on %s", self.incident_id)
            self._escalate(f"agent internal error: {type(exc).__name__}: {exc}")
        finally:
            with _runs_lock:
                if _runs.get(self.incident_id) is self:
                    _runs.pop(self.incident_id, None)

    def _run(self) -> None:
        inc_id = self.incident_id
        tickets.set_status(inc_id, tickets.INVESTIGATING, actor="agent", reason="RootFix agent picked up the incident")
        try:
            self.provider = make_provider(self.scenario, self.provider_name)
        except ProviderError as exc:
            raise Escalate(f"LLM provider unavailable ({exc}); handing to on-call") from exc
        audit.append("agent", "agent.started", incident_id=inc_id,
                     result={"provider": self.provider.name, "model": self.provider.model})
        trace(inc_id, "plan", "Plan: gather evidence (logs, deploys, diff, knowledge base) → record a decision → "
                              "request the least risky fix → verify on live metrics",
              {"provider": self.provider.name, "model": self.provider.model})
        narrate(inc_id, "Reading the incident record…")
        first = tool_server.invoke("get_incident", {}, inc_id)
        trace(inc_id, "tool", "Read the incident record", {"tool": "get_incident", "args": {}, "result": first.ui()})
        if first.flags:
            trace(inc_id, "warning", f"⚠ {len(first.flags)} untrusted instruction(s) found in the incident's sample logs; "
                                     "treated as data and ignored", {"flags": first.flags, "result_id": first.id})
        policy = None
        if self.memory_incident and llm_config()["memory_restart_first"]:
            policy = MEMORY_RESTART_FIRST_POLICY
            trace(inc_id, "plan", "On-call policy for memory incidents: mitigate first (restart), verify, "
                                  "then fix the root cause if memory keeps rising", {"policy": "memory_restart_first"})
        self.messages = [{"role": "user", "content": briefing(first.wrapped, first.id, policy)}]

        while not self.done and not self.cancelled.is_set():
            self._check_budget()
            resp = self._chat()
            self.steps += 1
            self.messages.append(resp.to_message())
            if resp.text:
                trace(inc_id, "thought", mask(resp.text)[:600])
                narrate(inc_id, mask(resp.text.splitlines()[0])[:200])
            if not resp.tool_calls:
                self.nudges += 1
                if self.nudges > 2:
                    raise Escalate("agent stopped without reaching a decision")
                self.messages.append({"role": "user", "content":
                                      "Continue the investigation with tools. When ready, call record_decision and then "
                                      "the chosen action (or escalate)."})
                continue
            for call in resp.tool_calls:
                if self.done or self.cancelled.is_set():
                    break
                content = self._handle(call)
                self.messages.append({"role": "tool", "tool_call_id": call.id, "name": call.name, "content": content})

    def _check_budget(self) -> None:
        if self.steps >= settings.max_steps:
            raise Escalate(f"step limit reached ({settings.max_steps} model turns)")
        if time.time() - self.started > settings.agent_budget_s:
            raise Escalate(f"time budget exhausted ({settings.agent_budget_s}s)")

    def _chat(self) -> LLMResponse:
        tools = list(TOOLS.values())
        delays = [2, 5]
        for attempt in range(len(delays) + 1):
            try:
                return self.provider.chat(SYSTEM_PROMPT, self.messages, tools)
            except ProviderError as exc:
                log.warning("provider error (attempt %d): %s", attempt + 1, exc)
                if attempt == len(delays):
                    raise Escalate(f"LLM provider unavailable after retries: {exc}") from exc
                trace(self.incident_id, "error", f"Model call failed, retrying in {delays[attempt]}s")
                time.sleep(delays[attempt])
        raise Escalate("unreachable")

    # ------------------------------------------------------------ tool dispatch
    def _handle(self, call: ToolCall) -> str:
        name, args = call.name, call.args or {}
        if name in ACTION_TOOLS:
            return self._act(call)
        if name == "escalate":
            try:
                clean = validate("escalate", args)
            except ValidationError as exc:
                return f"ERROR: {exc}"
            self._escalate(clean["reason"], clean["summary"])
            return "escalated"
        try:
            res = tool_server.invoke(name, args, self.incident_id)
        except (ValidationError, GateError) as exc:
            trace(self.incident_id, "error", f"{name} rejected: {exc}", {"tool": name, "args": mask(str(args))})
            return f"ERROR: {exc}"
        if name == "record_decision":
            return self._on_decision(res.data)
        summary = _tool_summary(name, res.args, res.text)
        trace(self.incident_id, "tool", summary, {"tool": name, "args": res.args, "result": res.ui()})
        if res.flags:
            trace(self.incident_id, "warning", f"⚠ {len(res.flags)} untrusted instruction(s) found in {name} output; "
                                               "treated as data and ignored", {"flags": res.flags, "result_id": res.id})
        return res.wrapped

    def _on_decision(self, data: dict) -> str:
        d = Decision.from_dict(data)
        self.decision, self.decision_used = d, False
        top = d.top
        trace(self.incident_id, "decision", f"Decision: {ACTION_WORDS.get(d.chosen_action, d.chosen_action)}. "
                                            f"Most likely cause: {top.cause} ({top.confidence:.0%})", data)
        narrate(self.incident_id, f"Most likely cause: {top.cause} ({top.confidence:.0%} confidence)")
        audit.append("agent", "decision.recorded", incident_id=self.incident_id, args={"chosen_action": d.chosen_action},
                     result={"top": top.cause, "confidence": top.confidence}, evidence=d.evidence)
        if self.steps >= 6 and top.confidence < 0.4:
            raise Escalate(f"low confidence after {self.steps} steps (top hypothesis {top.confidence:.0%})")
        return "decision recorded"

    # ------------------------------------------------------------ actions
    def _act(self, call: ToolCall) -> str:
        inc_id, name = self.incident_id, call.name
        d = self.decision
        if d is None or self.decision_used or d.chosen_action != name:
            msg = f"call record_decision with chosen_action='{name}' immediately before this action"
            trace(inc_id, "error", f"{name} blocked: {msg}")
            audit.append("system", "action.blocked", incident_id=inc_id, tool=name, args=call.args,
                         result={"reason": "no matching record_decision"})
            return f"ERROR: {msg}."
        try:
            clean = validate(name, call.args or {})
        except ValidationError as exc:
            trace(inc_id, "error", f"{name} rejected by validator: {exc}")
            audit.append("agent", "tool.invalid", incident_id=inc_id, tool=name, args=call.args, result={"error": str(exc)})
            return f"ERROR: {exc}"
        if self.gated_actions >= settings.max_gated_actions:
            raise Escalate(f"limit of {settings.max_gated_actions} gated actions reached")
        if any(t.action == name and t.args == clean and t.outcome in ("rejected", "did_not_fix", "made_worse")
               for t in self.tried):
            return "ERROR: this exact action was already tried or rejected. Choose a different remedy or escalate."

        if name == "apply_patch":
            if self.patches >= settings.max_patches:
                raise Escalate(f"patch limit reached ({settings.max_patches})")
            self.patches += 1
            narrate(inc_id, "Testing the proposed patch on a temporary worktree…")
            applies, msg, tests = impl.check_patch(clean["unified_diff"])
            ok = applies and tests is not None and tests.passed
            trace(inc_id, "tests", f"Patch pre-check: {'tests passed' if ok else 'FAILED'}: {msg}",
                  {"applies": applies, "summary": msg, "output": mask(tests.output[-2000:]) if tests else ""})
            audit.append("agent", "patch.precheck", incident_id=inc_id, tool=name, args=clean,
                         result={"applies": applies, "passed": ok, "summary": msg})
            if not ok:
                self.patch_test_failures += 1
                self.tried.append(Attempt(name, {"patch": f"#{self.patches}"}, "tests_failed", msg))
                if self.patch_test_failures >= 2:
                    raise Escalate("patch tests failed twice")
                out = tests.output[-1500:] if tests else ""
                return f"Patch NOT submitted for approval: {msg}\n{mask(out)}\nFix the patch (copy context lines exactly) and try again."

        if not needs_approval(TOOLS[name], inc_id):
            return self._execute(name, clean, None)

        prev = impl.preview(name, clean)
        self.decision_used = True
        apr = approvals.create(
            inc_id, name, clean, diff_preview=mask(prev["diff"]), risk=prev["risk"], evidence=d.evidence,
            hypothesis=d.top.cause, confidence=d.top.confidence, expected_effect=d.expected_effect or "",
            rollback_plan=prev["rollback_plan"], summary=prev["summary"])
        self.gated_actions += 1
        tickets.set_status(inc_id, tickets.AWAITING, actor="agent", reason=prev["summary"])
        trace(inc_id, "approval", f"Approval requested: {prev['summary']}", apr)
        narrate(inc_id, f"Waiting for human approval: {prev['summary']}")
        _fire("awaiting", inc_id, self)

        rec = approvals.wait(apr["id"], settings.approval_timeout_s, self.cancelled)
        if self.cancelled.is_set():
            self.done = True
            return "cancelled"
        if rec["status"] == approvals.EXPIRED:
            raise Escalate(f"no approval decision for {apr['id']} within {settings.approval_timeout_s}s")
        if rec["status"] == approvals.REJECTED:
            self.tried.append(Attempt(name, clean, "rejected", f"by {rec['approver']}: {rec['reason']}", apr["id"]))
            tickets.set_status(inc_id, tickets.INVESTIGATING, actor=rec["approver"],
                               reason=f"rejected {ACTION_WORDS[name]}: {rec['reason']}")
            trace(inc_id, "rejected", f"{rec['approver']} rejected the {ACTION_WORDS[name]}: “{rec['reason']}”", rec)
            narrate(inc_id, f"{rec['approver']} rejected the {ACTION_WORDS[name]}. Re-planning…")
            return (f"REJECTED by {rec['approver']}: {rec['reason']}\nDo not request this action again.\n"
                    f"Attempts so far:\n{self._tried_text()}\nChoose the next remedy in the policy order, or escalate.")
        trace(inc_id, "approved", f"{rec['approver']} approved: “{rec['reason']}”", rec)
        return self._execute(name, clean, rec)

    def _execute(self, name: str, args: dict, rec: dict | None) -> str:
        inc_id = self.incident_id
        apr_id = rec["id"] if rec else None
        self.decision_used = True
        pre = gitinfo.current_deploy()
        pre_ref = pre["tag"] or gitinfo.repo().head.commit.hexsha
        before = verifier.baseline()
        tickets.set_status(inc_id, tickets.RESOLVING, actor=rec["approver"] if rec else "agent",
                           reason=f"executing {ACTION_WORDS[name]}")
        narrate(inc_id, f"Executing the {ACTION_WORDS[name]}…")
        try:
            res = tool_server.invoke(name, args, inc_id, approval_id=apr_id)
        except (GateError, ValidationError) as exc:
            trace(inc_id, "error", f"{name} refused by tool server: {exc}")
            tickets.set_status(inc_id, tickets.INVESTIGATING, actor="system", reason=str(exc)[:200])
            self.tried.append(Attempt(name, args, "invalid", str(exc), apr_id))
            return f"ERROR: {exc}"
        trace(inc_id, "tool", _tool_summary(name, res.args, res.text), {"tool": name, "args": res.args, "result": res.ui()})
        tickets.set_status(inc_id, tickets.VERIFYING, actor="system", reason="watching live metrics")
        v = verifier.verify(inc_id, memory_incident=self.memory_incident, before=before, cancelled=self.cancelled)
        db.execute("UPDATE incidents SET verification = ? WHERE id = ?", (db.dumps(v), inc_id))
        audit.append("system", "verification", incident_id=inc_id, tool=name, approval_id=apr_id,
                     result={"recovered": v["recovered"], "measured": v["measured"], "checks": v["checks"]})
        if self.cancelled.is_set():
            self.done = True
            return "cancelled"
        if v["recovered"]:
            self.tried.append(Attempt(name, args, "resolved", "verified", apr_id, v))
            trace(inc_id, "verified", f"Recovery verified: checkout errors {v['measured']['error_rate_avg']:.1%} "
                                      f"for {v['window_s']}s, p95 {v['measured']['p95_ms_max']:.0f} ms", v)
            tickets.set_status(inc_id, tickets.RESOLVED, actor="system", reason="recovery verified on live metrics")
            narrate(inc_id, "Recovery verified on live metrics. Writing the report…")
            self.done = True
            _fire("resolved", inc_id, self)
            return "Verified: the service recovered. Incident resolved. Stop here."
        outcome = "did_not_fix"
        detail = f"measured {v['measured']}"
        if v["worse"] and name != "restart_service":
            outcome = "made_worse"
            self._auto_rollback(pre_ref, apr_id)
            detail += f"; metrics got worse, automatically restored {pre_ref}"
        elif self.memory_incident and name == "restart_service" and not v["checks"].get("memory_not_rising", True):
            detail += "; memory is rising again, so the restart only treated the symptom"
        self.tried.append(Attempt(name, args, outcome, detail, apr_id, v))
        if outcome == "made_worse":
            why = f"the {ACTION_WORDS[name]} made things worse; automatically restored {pre_ref}"
        elif self.memory_incident and name == "restart_service" and not v["checks"].get("memory_not_rising", True):
            why = (f"memory is climbing again ({v['measured']['memory_slope_mb_per_min']:.0f} MB/min), "
                   "so the restart only treated the symptom")
        else:
            why = (f"checkout errors still at {v['measured']['error_rate_avg']:.0%} after the {ACTION_WORDS[name]}, "
                   "so the change was not enough")
        trace(inc_id, "not_fixed", f"Did not fix: {why}", v)
        tickets.set_status(inc_id, tickets.INVESTIGATING, actor="system", reason=f"verification failed after {ACTION_WORDS[name]}")
        narrate(inc_id, f"Did not fix: {why}. Re-planning…")
        return (f"Action executed but verification FAILED ({outcome}): {detail}\nAttempts so far:\n{self._tried_text()}\n"
                "Re-plan: investigate further and choose the next remedy, or escalate.")

    def _auto_rollback(self, ref: str, apr_id: str | None) -> None:
        """Restore the pre-change version: the rollback plan the approver signed off on."""
        audit.append("system", "auto_rollback", incident_id=self.incident_id, approval_id=apr_id, args={"to": ref},
                     result={"reason": "metrics worse after approved change; executing the approved rollback plan"})
        impl.restore_ref(self.incident_id, ref)
        trace(self.incident_id, "auto_rollback", f"Metrics got worse: automatically restored {ref} (approved rollback plan)")

    # ------------------------------------------------------------ escalation
    def _tried_text(self) -> str:
        return "\n".join(t.line() for t in self.tried) or "(none)"

    def _escalate(self, reason: str, summary: str = "") -> None:
        if self.done:
            return
        self.done = True
        inc = tickets.get(self.incident_id)
        if inc is None or inc["status"] in (tickets.RESOLVED, tickets.CLOSED, tickets.ESCALATED):
            return
        d = self.decision
        structured = {
            "reason": reason,
            "agent_summary": summary,
            "hypotheses": [h.__dict__ for h in d.hypotheses] if d else [],
            "evidence": d.evidence if d else [],
            "attempts": [{"action": t.action, "args": t.args, "outcome": t.outcome, "detail": t.detail,
                          "approval_id": t.approval_id} for t in self.tried],
            "steps": self.steps,
        }
        try:
            tool_server.invoke("escalate", {"reason": reason, "summary": db.dumps(structured)}, self.incident_id,
                               actor="agent" if summary else "system")
        except Exception:  # noqa: BLE001
            log.exception("escalate tool failed; setting status directly")
            tickets.set_status(self.incident_id, tickets.ESCALATED, actor="system", reason=reason)
        db.execute("UPDATE incidents SET escalation = ? WHERE id = ?", (db.dumps(structured), self.incident_id))
        trace(self.incident_id, "escalation", f"Escalated to on-call: {reason}", structured)
        narrate(self.incident_id, f"Escalated to the on-call lead: {reason}")
        _fire("escalated", self.incident_id, self)


def _tool_summary(name: str, args: dict, text: str) -> str:
    first = (text.splitlines() or [""])[0]
    return {
        "get_incident": "Read the incident record",
        "query_metrics": f"Queried {args.get('metric')} for {args.get('endpoint')} over {args.get('window_s')}s",
        "read_logs": f"Read {args.get('level') or 'all'} logs from the last {args.get('since_s')}s"
                     + (f" containing “{args['contains']}”" if args.get("contains") else ""),
        "list_deploys": f"Listed the last {args.get('n')} deploys",
        "git_diff": f"Compared {args.get('from_ref')} → {args.get('to_ref')}",
        "read_file": f"Read {args.get('path')} lines {args.get('start')}-{args.get('end')}",
        "search_knowledge_base": f"Searched runbooks for “{args.get('query')}”",
        "run_tests": f"Ran the test suite at {args.get('ref')}: {first.split(': ', 1)[-1][:80]}",
        "restart_service": "Restarted the shop",
        "revert_config": f"Reverted {args.get('key')} to its {args.get('to_deploy')} value",
        "rollback_deploy": f"Rolled back to {args.get('to_tag')}",
        "apply_patch": "Applied the code patch",
    }.get(name, name)
