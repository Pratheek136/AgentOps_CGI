import { useEffect, useState } from "react";
import { marked } from "marked";
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { CheckCircle2, Download, ShieldCheck, ShieldX, XCircle } from "lucide-react";
import { getJSON } from "../api";
import { clock, dur, inr, pct } from "../format";
import type { Incident } from "../types";

export function ReportPanel({ inc }: { inc: Incident | null }) {
  const [md, setMd] = useState<string | null>(null);
  const [imp, setImp] = useState<any>(null);
  useEffect(() => {
    if (!inc) return;
    getJSON(`/api/incidents/${inc.id}/report`).then((r) => setMd(r.markdown)).catch(() => setMd(null));
    getJSON(`/api/incidents/${inc.id}/impact`).then(setImp).catch(() => {});
  }, [inc?.id, inc?.status]);
  if (!inc) return <div className="muted">No incident yet.</div>;
  return (
    <div className="report" data-testid="report">
      {imp && (
        <div className="kpi-tiles">
          <Kpi label="Disruption" value={`${imp.disruption_minutes.toFixed(1)} min`} />
          <Kpi label="Failed orders" value={String(imp.failed_checkouts)} />
          <Kpi label="₹ at risk" value={inr(imp.rupees_at_risk)} />
          <Kpi label="SLA" value={imp.sla_resolve_met == null ? "Open" : imp.sla_resolve_met ? "Met" : "Missed"}
            icon={imp.sla_resolve_met ? <CheckCircle2 size={18} /> : imp.sla_resolve_met === false ? <XCircle size={18} /> : null}
            tone={imp.sla_resolve_met ? "ok" : imp.sla_resolve_met === false ? "bad" : undefined} />
          <Kpi label="Time to resolve" value={dur(imp.time_to_resolve_s)} />
        </div>
      )}
      {md ? (
        <>
          <div className="report-actions">
            <a className="btn btn-primary" href={`/api/incidents/${inc.id}/report.md`} download data-testid="download"><Download size={16} /> Download postmortem (.md)</a>
            <span className="muted small">Figures are synthetic demo data computed from the database; the AI writes narrative only.</span>
          </div>
          <article className="markdown" dangerouslySetInnerHTML={{ __html: marked.parse(md) as string }} />
        </>
      ) : <div className="muted">The postmortem is generated automatically when the incident is resolved or escalated.</div>}
    </div>
  );
}

function Kpi({ label, value, icon, tone }: { label: string; value: string; icon?: any; tone?: "ok" | "bad" }) {
  return (
    <div className={`kpi-tile ${tone ? `kpi-${tone}` : ""}`}>
      <div className="kpi-tile-label">{label}</div>
      <div className="kpi-tile-value">{icon} {value}</div>
    </div>
  );
}

export function AuditPanel({ version }: { version: number }) {
  const [rows, setRows] = useState<any[]>([]);
  const [chain, setChain] = useState<any>(null);
  useEffect(() => {
    getJSON<any[]>("/api/audit?limit=300").then(setRows).catch(() => {});
    getJSON("/api/audit/verify").then(setChain).catch(() => {});
  }, [version]);
  return (
    <div data-testid="audit">
      {chain && (chain.ok ? (
        <div className="chain chain-ok"><ShieldCheck size={18} /> Audit chain verified ✓: {chain.count} entries, each SHA-256 linked to the previous one</div>
      ) : (
        <div className="chain chain-bad"><ShieldX size={18} /> Audit chain BROKEN at entry #{chain.broken_at}: {chain.reason}</div>
      ))}
      <table className="table">
        <thead><tr><th>#</th><th>Time</th><th>Incident</th><th>Actor</th><th>Action</th><th>Tool</th><th>Approval</th><th>Hash</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.seq} className={r.action.includes("rejected") || r.action.includes("injection") ? "row-warn" : ""}>
              <td>{r.seq}</td><td>{clock(r.ts)}</td><td>{r.incident_id ?? ""}</td><td>{r.actor}</td>
              <td>{r.action}</td><td>{r.tool ?? ""}</td><td>{r.approval_id ?? ""}</td><td><code>{r.hash.slice(0, 10)}</code></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const P_COLORS: Record<string, string> = { P1: "var(--p1)", P2: "var(--p2)", P3: "var(--p3)", P4: "var(--p4)" };

export function OverviewPanel({ version }: { version: number }) {
  const [o, setO] = useState<any>(null);
  useEffect(() => { getJSON("/api/overview").then(setO).catch(() => {}); }, [version]);
  if (!o) return <div className="skeleton" style={{ height: 200 }} />;
  const bars = Object.entries(o.by_priority).map(([p, n]) => ({ p, n }));
  return (
    <div data-testid="overview">
      <div className="kpi-tiles">
        <Kpi label="Incidents" value={String(o.incidents)} />
        <Kpi label="Mean time to resolve" value={dur(o.mttr_s)} />
        <Kpi label="Resolved without escalation" value={pct(o.resolved_without_escalation_pct)} />
        <Kpi label="Approvals / rejections" value={`${o.approvals} / ${o.rejections}`} />
        <Kpi label="Total ₹ at risk" value={inr(o.rupees_at_risk_total)} />
      </div>
      <div className="overview-grid">
        <div className="card pad">
          <h4>Incidents by priority</h4>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={bars} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
              <XAxis dataKey="p" tick={{ fill: "var(--ink)", fontSize: 13 }} stroke="var(--border)" />
              <YAxis allowDecimals={false} tick={{ fill: "var(--muted)", fontSize: 12 }} stroke="var(--border)" />
              <Tooltip cursor={{ fill: "var(--tint)" }} />
              <Bar dataKey="n" name="Incidents" radius={[4, 4, 0, 0]} maxBarSize={48}>
                {bars.map((b) => <Cell key={b.p} fill={P_COLORS[b.p]} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="card pad"><h4>Incident history</h4><HistoryTable rows={o.history} /></div>
      </div>
      <div className="muted xs">All figures: {o.label}.</div>
    </div>
  );
}

export function HistoryTable({ rows }: { rows: any[] }) {
  if (!rows?.length) return <div className="muted">No incidents yet.</div>;
  return (
    <table className="table">
      <thead><tr><th>ID</th><th>Priority</th><th>Status</th><th>Signal</th><th>Opened</th><th>Resolve time</th><th>₹ at risk</th><th>SLA</th></tr></thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.id}>
            <td><b>{r.id}</b></td><td><span className={`badge badge-${(r.priority ?? "p4").toLowerCase()}`}>{r.priority}</span></td>
            <td>{r.status}</td><td className="ellipsis">{r.signal}</td><td>{clock(r.created_at)}</td>
            <td>{dur(r.time_to_resolve_s)}</td><td>{inr(r.rupees_at_risk)}</td>
            <td>{r.sla_met == null ? "—" : r.sla_met ? "Met ✓" : "Missed ✗"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function HistoryPanel({ version }: { version: number }) {
  const [rows, setRows] = useState<any[]>([]);
  useEffect(() => { getJSON<any>("/api/overview").then((o) => setRows(o.history)).catch(() => {}); }, [version]);
  return <div data-testid="history"><HistoryTable rows={rows} /></div>;
}
