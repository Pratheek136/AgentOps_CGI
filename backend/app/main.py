"""FastAPI app: REST API + SSE stream for the dashboard."""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from . import approvals, audit, db, demo, retrieval, tickets
from .tools import server as tool_server
from .tools.gate import GateError
from .tools.registry import TOOLS, ValidationError
from .agent import loop as agent_loop
from .alerts import engine
from . import impact, ingest, notify, report
from fastapi.responses import PlainTextResponse
import threading
from .config import USERS, llm_config, paths, settings
from .events import bus, sse_format
from .monitor import monitor, series
from .runtime import get_shop_runtime, get_traffic_runtime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("rootfix")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    bus.bind_loop(asyncio.get_running_loop())
    if paths.shop_repo.exists():
        await asyncio.to_thread(get_shop_runtime().start)
        await asyncio.to_thread(get_traffic_runtime().start)
    else:
        log.warning("shop_repo missing: run `python scripts/demo.py seed`")
    monitor.on_sample.append(engine.on_sample)
    ingest.on_triaged.append(notify.on_triaged)
    ingest.on_triaged.append(lambda inc_id: agent_loop.start(inc_id, demo.current_scenario, demo.provider_override))
    agent_loop.hooks["awaiting"].append(notify.on_awaiting)
    agent_loop.hooks["resolved"] += [notify.on_resolved, report.generate, _schedule_close]
    agent_loop.hooks["escalated"] += [notify.on_escalated, report.generate]
    monitor.start()
    bus.publish("system", {"message": "backend started"})
    yield
    monitor.stop()
    await asyncio.to_thread(get_traffic_runtime().stop)
    await asyncio.to_thread(get_shop_runtime().stop)


def _schedule_close(incident_id: str, run=None) -> None:
    def close() -> None:
        inc = tickets.get(incident_id)
        if inc and inc["status"] == tickets.RESOLVED:
            tickets.set_status(incident_id, tickets.CLOSED, actor="system",
                               reason=f"auto-closed {settings.auto_close_s}s after verified resolution")
    t = threading.Timer(settings.auto_close_s, close)
    t.daemon = True
    t.start()


app = FastAPI(title="RootFix", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health")
def health() -> dict:
    shop = get_shop_runtime().status()
    return {
        "ok": True,
        "time": time.time(),
        "runtime": settings.runtime,
        "llm_provider": llm_config()["provider"],
        "demo_mode": settings.demo_mode,
        "shop": {"running": shop.running, "healthy": shop.healthy, "pid": shop.pid},
    }


@app.get("/api/users")
def users() -> list[dict]:
    return [{"name": u.name, "role": u.role, "can_approve": u.can_approve} for u in USERS]


@app.get("/api/events")
async def events(request: Request) -> StreamingResponse:
    q = bus.subscribe()

    async def gen():
        try:
            yield "retry: 2000\n\n"
            yield sse_format({"id": 0, "type": "hello", "ts": time.time(), "data": {"ok": True}})
            while True:
                if await request.is_disconnected():
                    break
                try:
                    evt = await asyncio.wait_for(q.get(), timeout=15)
                    yield sse_format(evt)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            bus.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/metrics")
def metrics(window_s: int = 300) -> dict:
    return series(window_s)


@app.get("/api/metrics/latest")
def metrics_latest() -> dict:
    return monitor.latest


@app.post("/api/demo/fault/{n}")
def demo_fault(n: int, provider: str | None = None) -> dict:
    try:
        return demo.inject_fault(n, provider)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/demo/reset")
def demo_reset() -> dict:
    agent_loop.cancel_all()
    monitor.reset_state()
    engine.reset()
    return demo.reset()


# ---------------------------------------------------------------- incidents
@app.get("/api/incidents")
def incidents() -> list[dict]:
    rows = db.query("SELECT id FROM incidents ORDER BY seq DESC")
    return [tickets.view(r["id"]) for r in rows]


@app.get("/api/incidents/active")
def active_incident() -> dict | None:
    inc = tickets.open_incident(include_escalated=True)
    if inc is None:
        inc = db.one("SELECT * FROM incidents ORDER BY seq DESC LIMIT 1")
    return tickets.view(inc["id"]) if inc else None


@app.get("/api/incidents/{incident_id}")
def incident(incident_id: str) -> dict:
    inc = tickets.view(incident_id)
    if inc is None:
        raise HTTPException(404, "no such incident")
    return inc


# ---------------------------------------------------------------- KB + audit
@app.get("/api/kb/search")
def kb_search(q: str, k: int = 3) -> list[dict]:
    return retrieval.search(q, k)


@app.get("/api/kb/{doc_id}")
def kb_doc(doc_id: str) -> dict:
    doc = retrieval.get(doc_id)
    if doc is None:
        raise HTTPException(404, "no such KB document")
    return doc


@app.get("/api/audit")
def audit_log(incident_id: str | None = None, limit: int = 500) -> list[dict]:
    return audit.entries(incident_id, limit)


@app.get("/api/audit/verify")
def audit_verify() -> dict:
    return audit.verify_chain()


# ---------------------------------------------------------------- tool server
class ToolCall(BaseModel):
    incident_id: str | None = None
    args: dict = {}
    approval_id: str | None = None
    actor: str = "agent"


@app.get("/api/tools")
def list_tools() -> list[dict]:
    return [{"name": t.name, "tier": t.tier, "description": t.description} for t in TOOLS.values()]


@app.post("/api/tools/{name}")
def call_tool(name: str, call: ToolCall) -> dict:
    try:
        res = tool_server.invoke(name, call.args, call.incident_id, call.approval_id, call.actor)
    except GateError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    return res.ui()


# ---------------------------------------------------------------- approvals
class Decision(BaseModel):
    approver: str
    decision: str  # approve | reject
    reason: str


@app.get("/api/approvals")
def list_approvals(status: str | None = None, incident_id: str | None = None) -> list[dict]:
    if status == "pending":
        return approvals.pending(incident_id)
    if incident_id:
        return approvals.for_incident(incident_id)
    return [approvals.get(r["id"]) for r in db.query("SELECT id FROM approvals ORDER BY created_at DESC")]


@app.post("/api/approvals/{approval_id}/decide")
def decide_approval(approval_id: str, d: Decision) -> dict:
    if d.decision not in ("approve", "reject"):
        raise HTTPException(422, "decision must be approve or reject")
    try:
        return approvals.decide(approval_id, d.approver, d.decision == "approve", d.reason)
    except approvals.ApprovalError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@app.get("/api/incidents/{incident_id}/trace")
def incident_trace(incident_id: str) -> list[dict]:
    rows = db.query("SELECT * FROM trace WHERE incident_id = ? ORDER BY id", (incident_id,))
    for r in rows:
        r["data"] = db.loads(r["data"], None)
    return rows


@app.post("/api/agent/start/{incident_id}")
def agent_start(incident_id: str) -> dict:
    if tickets.get(incident_id) is None:
        raise HTTPException(404, "no such incident")
    agent_loop.start(incident_id, demo.current_scenario, demo.provider_override)
    return {"started": incident_id}


# ---------------------------------------------------------------- outcome reporting
@app.get("/api/incidents/{incident_id}/impact")
def incident_impact(incident_id: str) -> dict:
    inc = tickets.get(incident_id)
    if inc is None:
        raise HTTPException(404, "no such incident")
    frozen = db.loads(inc["impact_json"])
    return frozen or impact.compute(incident_id)


@app.get("/api/incidents/{incident_id}/report")
def incident_report(incident_id: str) -> dict:
    inc = tickets.get(incident_id)
    if inc is None:
        raise HTTPException(404, "no such incident")
    return {"incident_id": incident_id, "markdown": inc["report_md"]}


@app.get("/api/incidents/{incident_id}/report.md")
def incident_report_md(incident_id: str) -> PlainTextResponse:
    inc = tickets.get(incident_id)
    if inc is None or not inc["report_md"]:
        raise HTTPException(404, "no report yet")
    return PlainTextResponse(inc["report_md"], media_type="text/markdown",
                             headers={"Content-Disposition": f'attachment; filename="{incident_id}-postmortem.md"'})


class CloseRequest(BaseModel):
    user: str
    reason: str = "closed manually"


@app.post("/api/incidents/{incident_id}/close")
def incident_close(incident_id: str, req: CloseRequest) -> dict:
    try:
        return tickets.set_status(incident_id, tickets.CLOSED, actor=req.user, reason=req.reason)
    except tickets.TransitionError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/notifications")
def notifications(limit: int = 50) -> list[dict]:
    return notify.feed(limit)


@app.get("/api/overview")
def overview() -> dict:
    rows = db.query("SELECT * FROM incidents ORDER BY seq DESC")
    by_p = {p: 0 for p in ("P1", "P2", "P3", "P4")}
    resolved_times, rupees, escalated, history = [], 0.0, 0, []
    for r in rows:
        if r["priority"]:
            by_p[r["priority"]] += 1
        imp = db.loads(r["impact_json"]) or impact.compute(r["id"])
        rupees += imp.get("rupees_at_risk", 0)
        if r["resolved_at"]:
            resolved_times.append(r["resolved_at"] - r["created_at"])
        if r["escalated_at"]:
            escalated += 1
        history.append({"id": r["id"], "priority": r["priority"], "status": r["status"], "signal": r["signal"],
                        "created_at": r["created_at"], "time_to_resolve_s": imp.get("time_to_resolve_s"),
                        "rupees_at_risk": imp.get("rupees_at_risk"), "sla_met": imp.get("sla_resolve_met"),
                        "failed_checkouts": imp.get("failed_checkouts")})
    apr = db.one("SELECT SUM(status = 'approved') AS a, SUM(status = 'rejected') AS r, COUNT(*) AS n FROM approvals")
    done = len(resolved_times) + escalated
    return {
        "label": impact.LABEL, "incidents": len(rows), "by_priority": by_p,
        "mttr_s": round(sum(resolved_times) / len(resolved_times), 1) if resolved_times else None,
        "resolved_without_escalation_pct": round(len(resolved_times) / done, 4) if done else None,
        "approvals": apr["a"] or 0, "rejections": apr["r"] or 0, "approval_requests": apr["n"] or 0,
        "rupees_at_risk_total": round(rupees, 2), "history": history,
    }


# ---------------------------------------------------------------- evidence lookups (masked)
@app.get("/api/evidence/{evidence_id:path}")
def evidence(evidence_id: str, incident_id: str | None = None) -> dict:
    from . import logsource
    from .security import detect_injection, mask
    if evidence_id.startswith("KB:"):
        doc = retrieval.get(evidence_id[3:])
        if doc is None:
            raise HTTPException(404, "no such KB document")
        return {"id": evidence_id, "kind": "kb", "title": f"{doc['id']}: {doc['title']}", "text": doc["text"]}
    if evidence_id.startswith("tr-"):
        r = db.one("SELECT * FROM tool_results WHERE id = ? AND (? IS NULL OR incident_id = ?) ORDER BY seq DESC LIMIT 1",
                   (evidence_id, incident_id, incident_id))
        if r is None:
            raise HTTPException(404, "no such tool result")
        return {"id": evidence_id, "kind": "tool", "title": f"{evidence_id}: {r['tool']}({mask(r['args'])})",
                "text": r["output"], "flagged": bool(r["flagged"])}
    if evidence_id.startswith("log#"):
        try:
            n = int(evidence_id[4:])
        except ValueError as exc:
            raise HTTPException(400, "bad log id") from exc
        recs = [x for x in logsource.read(since_s=3600, limit=200, contains=None, level="ERROR") if x["line"] == n]
        if not recs:
            recs = [x for x in logsource.read(since_s=3600, limit=200) if x["line"] == n]
        if not recs:
            raise HTTPException(404, "log line not found (older than 1h?)")
        text = mask(logsource.format_record(recs[0]))
        return {"id": evidence_id, "kind": "log", "title": f"Shop log line {n}", "text": text,
                "flagged": bool(detect_injection(text))}
    raise HTTPException(400, "unknown evidence id format")
