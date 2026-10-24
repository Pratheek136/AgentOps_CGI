import { useEffect, useRef, useState } from "react";
import { CheckCircle2, ShieldAlert, Undo2, XCircle } from "lucide-react";
import { postJSON } from "../api";

export type Approval = {
  id: string; incident_id: string; status: string; tool: string; args: any; diff_preview: string; risk: string;
  evidence: string[]; hypothesis: string; confidence: number; expected_effect: string; rollback_plan: string;
  summary: string; approver: string | null; reason: string | null; created_at: number;
};
export type User = { name: string; role: string; can_approve: boolean };

export function DiffView({ diff }: { diff: string }) {
  if (!diff) return null;
  return (
    <pre className="diff" data-testid="diff">
      {diff.split("\n").map((l, i) => (
        <div key={i} className={l.startsWith("+") && !l.startsWith("+++") ? "add" : l.startsWith("-") && !l.startsWith("---") ? "del" : l.startsWith("@@") ? "hunk" : ""}>{l || " "}</div>
      ))}
    </pre>
  );
}

export function ApprovalPanel({ apr, user, onEvidence, focusRef }: {
  apr: Approval; user: User | null; onEvidence?: (id: string) => void; focusRef?: React.RefObject<HTMLTextAreaElement>;
}) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const local = useRef<HTMLTextAreaElement>(null);
  const ref = focusRef ?? local;
  useEffect(() => { setReason(""); setErr(null); }, [apr.id]);

  const decide = async (decision: "approve" | "reject") => {
    if (!user) return;
    if (!reason.trim()) { setErr("Please give a reason. It goes into the audit log."); ref.current?.focus(); return; }
    setBusy(true); setErr(null);
    try {
      await postJSON(`/api/approvals/${apr.id}/decide`, { approver: user.name, decision, reason });
    } catch (e: any) {
      setErr(e.message);
    } finally { setBusy(false); }
  };
  const canApprove = !!user?.can_approve;
  return (
    <section className="card approval pulse" data-testid="approval" id="approval-panel">
      <div className="approval-head">
        <ShieldAlert size={22} />
        <h2>Approval needed</h2>
        <span className={`risk risk-${apr.risk}`}>{apr.risk} risk</span>
        <span className="muted small">{apr.id}</span>
      </div>
      <div className="approval-action">{apr.summary}</div>
      <div className="approval-details">
      <div className="approval-why">
        <b>Why:</b> {apr.hypothesis} <span className="conf">({Math.round(apr.confidence * 100)}% confidence)</span>
      </div>
      <div className="chips">
        {apr.evidence.map((e) => <button key={e} className="chip" onClick={() => onEvidence?.(e)}>{e}</button>)}
      </div>
      <DiffView diff={apr.diff_preview} />
      <div className="approval-grid">
        <div><b>Expected effect</b><div>{apr.expected_effect || "—"}</div></div>
        <div><b><Undo2 size={14} /> Rollback plan</b><div>{apr.rollback_plan}</div></div>
      </div>
      </div>
      <label className="reason">
        <span>Reason (required, audited) · approving as <b>{user?.name ?? "—"}</b>{user && !canApprove && " (read-only role)"}</span>
        <textarea ref={ref} value={reason} onChange={(e) => setReason(e.target.value)} rows={2}
          placeholder="e.g. Diff matches the error logs; config revert is low risk" />
      </label>
      {err && <div className="error-text">{err}</div>}
      <div className="approval-buttons">
        <button className="btn btn-primary" disabled={busy || !canApprove} onClick={() => decide("approve")} data-testid="approve">
          <CheckCircle2 size={18} /> Approve
        </button>
        <button className="btn btn-secondary" disabled={busy || !canApprove} onClick={() => decide("reject")} data-testid="reject">
          <XCircle size={18} /> Reject
        </button>
      </div>
    </section>
  );
}
