import { useEffect, useRef, useState } from "react";
import { AlertTriangle, BadgeCheck, Brain, ChevronDown, ChevronRight, FlaskConical, ListChecks, MessageSquare,
  ShieldAlert, ShieldCheck, ShieldX, Siren, Undo2, Wrench, XCircle } from "lucide-react";

export type TraceItem = { id: number; incident_id: string; ts: number; kind: string; summary: string; data: any };

const ICONS: Record<string, any> = {
  plan: ListChecks, thought: MessageSquare, tool: Wrench, decision: Brain, approval: ShieldAlert,
  approved: ShieldCheck, rejected: ShieldX, verified: BadgeCheck, not_fixed: XCircle, escalation: Siren,
  warning: AlertTriangle, error: AlertTriangle, tests: FlaskConical, auto_rollback: Undo2,
};

const fmt = (ts: number) => new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

function Hypotheses({ data, onEvidence }: { data: any; onEvidence?: (id: string) => void }) {
  return (
    <div className="hyps">
      {data.hypotheses.map((h: any, i: number) => (
        <div key={i} className="hyp">
          <div className="hyp-row">
            <span className="hyp-cause">{h.cause}</span>
            <span className="hyp-conf">{Math.round(h.confidence * 100)}%</span>
          </div>
          <div className="conf-bar"><div style={{ width: `${h.confidence * 100}%` }} /></div>
          <div className="chips">{h.evidence.map((e: string) => <button key={e} className="chip" onClick={() => onEvidence?.(e)}>{e}</button>)}</div>
        </div>
      ))}
      <div className="muted small"><b>Why:</b> {data.rationale}</div>
    </div>
  );
}

function Step({ t, onEvidence }: { t: TraceItem; onEvidence?: (id: string) => void }) {
  const [open, setOpen] = useState(false);
  const Icon = ICONS[t.kind] ?? MessageSquare;
  const result = t.data?.result;
  const flagged = result?.flags?.length > 0 || t.kind === "warning";
  return (
    <li className={`step step-${t.kind}`}>
      <span className="step-icon"><Icon size={16} /></span>
      <div className="step-body">
        <div className="step-line">
          <span className="step-summary">{t.summary}</span>
          {result?.id && <span className="chip chip-static">{result.id}</span>}
          {flagged && <span className="badge-warn"><AlertTriangle size={13} /> untrusted instruction ignored</span>}
          <span className="step-time">{fmt(t.ts)}</span>
        </div>
        {t.kind === "decision" && t.data?.hypotheses && <Hypotheses data={t.data} onEvidence={onEvidence} />}
        {result?.text && (
          <>
            <button className="link" onClick={() => setOpen(!open)}>
              {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />} {open ? "Hide" : "Show"} details
            </button>
            {open && <pre className="tool-output">{result.text}</pre>}
          </>
        )}
      </div>
    </li>
  );
}

export function AgentTrace({ items, onEvidence, autoScroll = true }: { items: TraceItem[]; onEvidence?: (id: string) => void; autoScroll?: boolean }) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = box.current;
    if (autoScroll && el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [items.length, autoScroll]);
  return (
    <section className="card trace" data-testid="trace" id="trace">
      <h3>Agent trace <span className="muted xs">{items.length} steps · newest at the bottom</span></h3>
      <div className="trace-scroll" ref={box}>
        {items.length === 0 ? <div className="skeleton" style={{ height: 120 }} /> : (
          <ol className="steps">{items.map((t) => <Step key={t.id} t={t} onEvidence={onEvidence} />)}</ol>
        )}
      </div>
    </section>
  );
}
