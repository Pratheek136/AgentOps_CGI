import { useEffect, useState } from "react";
import { AlertTriangle, Brain, Database, FileText, Wrench, X } from "lucide-react";
import { getJSON } from "../api";

export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: any; wide?: boolean }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className={`modal ${wide ? "modal-wide" : ""}`} role="dialog" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <div className="modal-head"><h2>{title}</h2><button className="icon-btn" onClick={onClose} aria-label="Close"><X size={20} /></button></div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}

export function HowItWorks({ onClose }: { onClose: () => void }) {
  const stages = [
    { Icon: Database, t: "Ingest", d: "Monitoring alert + metrics, logs, deploy history and past incidents become one structured incident ticket." },
    { Icon: Brain, t: "Decide", d: "Rule-based priority (P1–P4) and SLA. The AI agent investigates with read-only tools and records hypotheses with confidence and evidence." },
    { Icon: Wrench, t: "Act", d: "Least risky fix first: config revert → rollback → restart → patch. Every change needs a named human approval." },
    { Icon: FileText, t: "Report", d: "Recovery verified on live metrics. Business impact in ₹, SLA met/missed, postmortem and stakeholder updates." },
  ];
  return (
    <Modal title="How RootFix works" onClose={onClose} wide>
      <div className="how-stages">
        {stages.map((s, i) => (
          <div key={s.t} className="how-stage"><div className="how-icon"><s.Icon size={22} /></div><b>{i + 1}. {s.t}</b><p>{s.d}</p></div>
        ))}
      </div>
      <div className="how-cols">
        <div>
          <h4>Responsible AI controls</h4>
          <ul>
            <li>Approval gate enforced in the tool server (HTTP 403 without an approved record), not in the prompt</li>
            <li>Least-privilege tool allowlist; no shell; argument validators</li>
            <li>Step, action and patch limits; time budget; escalation when unsure</li>
            <li>Automatic rollback if metrics get worse after a change</li>
            <li>Secret masking on every output; logs treated as untrusted data with prompt-injection detection</li>
            <li>SHA-256 hash-chained, append-only audit log</li>
            <li>Facts (₹, SLA, counts, priority) come from code, never from the LLM</li>
          </ul>
        </div>
        <div>
          <h4>Tech stack</h4>
          <ul>
            <li>Python, FastAPI, SQLite, scikit-learn TF-IDF retrieval</li>
            <li>Gemini / Grok via native function calling (pluggable), offline replay</li>
            <li>React + TypeScript + Recharts, live updates over Server-Sent Events</li>
            <li>Demo shop: Flask, real git deploy history, synthetic traffic</li>
          </ul>
          <p className="muted small">All data is synthetic.</p>
        </div>
      </div>
    </Modal>
  );
}

export function Shortcuts({ onClose }: { onClose: () => void }) {
  const rows = [["1–6", "Inject demo scenario"], ["R", "Reset demo"], ["A", "Focus the approval panel"], ["P", "Presenter mode"],
    ["O", "Overview tab"], ["H", "How RootFix works"], ["?", "This help"], ["Esc", "Close panels"]];
  return (
    <Modal title="Keyboard shortcuts" onClose={onClose}>
      <table className="table">
        <tbody>{rows.map(([k, d]) => <tr key={k}><td><kbd>{k}</kbd></td><td>{d}</td></tr>)}</tbody>
      </table>
    </Modal>
  );
}

export function EvidenceDrawer({ id, incidentId, onClose }: { id: string; incidentId?: string; onClose: () => void }) {
  const [ev, setEv] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    setEv(null); setErr(null);
    getJSON(`/api/evidence/${encodeURIComponent(id)}${incidentId ? `?incident_id=${incidentId}` : ""}`).then(setEv).catch((e) => setErr(e.message));
  }, [id, incidentId]);
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <aside className="drawer" data-testid="evidence">
      <div className="modal-head"><h2>Evidence <code>{id}</code></h2><button className="icon-btn" onClick={onClose} aria-label="Close"><X size={20} /></button></div>
      {err && <div className="error-text">{err}</div>}
      {!ev && !err && <div className="skeleton" style={{ height: 200 }} />}
      {ev && (
        <>
          <div className="drawer-title">{ev.title}</div>
          {ev.flagged && <div className="badge-warn"><AlertTriangle size={13} /> Contains text that looks like an instruction. Treated as untrusted data.</div>}
          <div className="muted xs">{ev.kind === "kb" ? "Knowledge base (synthetic runbook / postmortem)" : "Tool output: masked, untrusted data"}</div>
          <pre className="tool-output tall">{ev.text}</pre>
        </>
      )}
    </aside>
  );
}

export type Toast = { id: number; tone: "alert" | "approval" | "ok" | "warn"; text: string };

export function Toasts({ items, onDismiss }: { items: Toast[]; onDismiss: (id: number) => void }) {
  return (
    <div className="toasts" aria-live="polite">
      {items.map((t) => (
        <div key={t.id} className={`toast toast-${t.tone}`} onClick={() => onDismiss(t.id)}>{t.text}</div>
      ))}
    </div>
  );
}
