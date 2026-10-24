import { useEffect, useState } from "react";
import { AlertTriangle, BookOpen, CheckCircle2, Clock, GitCommit, Server } from "lucide-react";
import type { Incident } from "../types";
import { LIFECYCLE } from "../types";

export function PriorityBadge({ p }: { p: string | null }) {
  if (!p) return <span className="badge badge-p4">Unrated</span>;
  return <span className={`badge badge-${p.toLowerCase()}`}><AlertTriangle size={14} /> {p}</span>;
}

function fmtDur(s: number) {
  const sign = s < 0 ? "-" : "";
  s = Math.abs(Math.round(s));
  const m = Math.floor(s / 60), sec = s % 60;
  return `${sign}${m}:${String(sec).padStart(2, "0")}`;
}

export function SlaCountdown({ inc }: { inc: Incident }) {
  const [now, setNow] = useState(Date.now() / 1000);
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(t);
  }, []);
  const sla = inc.sla;
  const end = inc.resolved_at ?? inc.escalated_at ?? (sla.running ? now : inc.created_at + sla.elapsed_s);
  const used = (end - inc.created_at) / (sla.resolve_target_min * 60);
  const remaining = sla.resolve_due - end;
  const level = used >= 0.8 ? "red" : used >= 0.5 ? "amber" : "ok";
  if (inc.resolved_at) {
    const met = inc.resolved_at <= sla.resolve_due;
    return (
      <div className={`sla sla-${met ? "ok" : "red"}`} data-testid="sla">
        {met ? <CheckCircle2 size={18} /> : <AlertTriangle size={18} />}
        <span>SLA {met ? "met" : "missed"}: resolved in {fmtDur(inc.resolved_at - inc.created_at)} vs {sla.resolve_target_min}m target</span>
      </div>
    );
  }
  return (
    <div className={`sla sla-${level}`} data-testid="sla">
      <Clock size={18} />
      <span className="sla-time">{fmtDur(remaining)}</span>
      <span className="sla-label">left to resolve ({sla.resolve_target_min}m {sla.priority} target)</span>
      <div className="sla-bar"><div style={{ width: `${Math.min(100, used * 100)}%` }} /></div>
    </div>
  );
}

export function StatusTimeline({ inc }: { inc: Incident }) {
  const reached = new Set(inc.history.map((h) => h.to_status));
  const escalated = inc.status === "Escalated";
  const steps = escalated ? [...LIFECYCLE.filter((s) => reached.has(s)), "Escalated"] : LIFECYCLE;
  return (
    <div className="status-pills">
      {steps.map((s) => {
        const current = s === inc.status;
        const done = reached.has(s) && !current;
        return (
          <span key={s} className={`pill ${current ? "pill-current" : done ? "pill-done" : ""} ${s === "Escalated" ? "pill-escalated" : ""}`}>
            {done && <CheckCircle2 size={13} />} {s}
          </span>
        );
      })}
    </div>
  );
}

export function TicketCard({ inc, onEvidence, onCloseTicket }: { inc: Incident | null; onEvidence?: (id: string) => void; onCloseTicket?: () => void }) {
  if (!inc) return <div className="card ticket skeleton" style={{ height: 220 }} />;
  return (
    <section className={`card ticket ticket-${(inc.priority ?? "p4").toLowerCase()}`} data-testid="ticket" id="ticket">
      <div className="ticket-head">
        <div>
          <div className="ticket-id">{inc.id} <PriorityBadge p={inc.priority} /></div>
          <div className="ticket-signal">{inc.signal}</div>
        </div>
        <div className="ticket-side">
          <SlaCountdown inc={inc} />
          {onCloseTicket && (inc.status === "Resolved" || inc.status === "Escalated") && (
            <button className="btn btn-ghost small" onClick={onCloseTicket} data-testid="close-ticket">Close ticket</button>
          )}
        </div>
      </div>
      <StatusTimeline inc={inc} />
      <div className="ticket-facts">
        <div><Server size={16} /> <b>Service</b> {inc.service} · {inc.endpoints.join(", ")}</div>
        <div><GitCommit size={16} /> <b>Deploy</b> <code>{inc.deploy_tag ?? inc.deploy_sha}</code> (now) · last good <code>{inc.prev_tag ?? "—"}</code></div>
        <div className="muted small">{inc.priority_reason}</div>
      </div>
      <div className="kb-row">
        <BookOpen size={16} /> <b>Similar knowledge</b>
        {inc.kb_matches.map((m) => (
          <button key={m.id} className="chip" onClick={() => onEvidence?.(`KB:${m.id}`)} title={m.title}>KB:{m.id}</button>
        ))}
      </div>
    </section>
  );
}
