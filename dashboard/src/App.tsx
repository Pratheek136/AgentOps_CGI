import { useCallback, useEffect, useRef, useState } from "react";
import { Activity, Brain, CheckCircle2, Database, FileText, FlaskConical, HelpCircle, Info, Keyboard, MonitorPlay, ShieldCheck, Wifi, WifiOff, Wrench, X, XCircle } from "lucide-react";
import { getJSON, postJSON, Series } from "./api";
import { useEventStream, RFEvent } from "./sse";
import { HealthStrip } from "./components/HealthStrip";
import { DemoControls } from "./components/DemoControls";
import { TicketCard } from "./components/TicketCard";
import { AgentTrace, TraceItem } from "./components/AgentTrace";
import { Approval, ApprovalPanel, User } from "./components/ApprovalPanel";
import { StageStepper } from "./components/StageStepper";
import { ImpactCard } from "./components/ImpactCard";
import { Note, StakeholderFeed } from "./components/StakeholderFeed";
import { AuditPanel, HistoryPanel, OverviewPanel, ReportPanel } from "./components/Panels";
import { EvidenceDrawer, HowItWorks, Shortcuts, Toast, Toasts } from "./components/Overlays";
import type { Incident } from "./types";
import { clock, dur, inr } from "./format";

const IDLE_TEXT = "All systems operational. RootFix is watching 4 services.";
const STEP_MS = 1200; // every agent step stays visible for at least this long
type Tab = "report" | "audit" | "overview" | "history";
const TABS: { key: Tab; label: string }[] = [
  { key: "report", label: "Outcome report" }, { key: "audit", label: "Audit log" },
  { key: "overview", label: "Overview KPIs" }, { key: "history", label: "Incident history" },
];

export default function App() {
  const [series, setSeries] = useState<Series | null>(null);
  const [latest, setLatest] = useState<any>(null);
  const [inc, setInc] = useState<Incident | null>(null);
  const [trace, setTrace] = useState<TraceItem[]>([]);
  const [pending, setPending] = useState<Approval | null>(null);
  const [notes, setNotes] = useState<Note[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [user, setUser] = useState<User | null>(null);
  const [narration, setNarration] = useState(IDLE_TEXT);
  const [tab, setTab] = useState<Tab | null>(null);
  const [demoOpen, setDemoOpen] = useState(false);
  const [overlay, setOverlay] = useState<"how" | "keys" | null>(null);
  const [evidence, setEvidence] = useState<string | null>(null);
  const [presenter, setPresenter] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [version, setVersion] = useState(0);
  const [now, setNow] = useState(Date.now());
  const incId = useRef<string | null>(null);
  const queue = useRef<TraceItem[]>([]);
  const reasonRef = useRef<HTMLTextAreaElement>(null);

  const toast = useCallback((tone: Toast["tone"], text: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t.slice(-3), { id, tone, text }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4500);
  }, []);

  const loadSeries = useCallback(() => getJSON<Series>("/api/metrics?window_s=300").then(setSeries).catch(() => {}), []);
  const loadNotes = useCallback(() => getJSON<Note[]>("/api/notifications").then(setNotes).catch(() => {}), []);
  const loadSeq = useRef(0);
  const shownIds = useRef<Set<number>>(new Set());
  const loadIncident = useCallback(async () => {
    const seq = ++loadSeq.current;
    const i = await getJSON<Incident | null>("/api/incidents/active").catch(() => undefined);
    if (i === undefined || seq !== loadSeq.current) return; // ignore stale responses
    setInc(i);
    const changed = (i?.id ?? null) !== incId.current;
    incId.current = i?.id ?? null;
    if (!i) { setTrace([]); setPending(null); queue.current = []; shownIds.current = new Set(); return; }
    const items = await getJSON<TraceItem[]>(`/api/incidents/${i.id}/trace`).catch(() => null);
    if (items && seq === loadSeq.current) {
      if (changed) {
        queue.current = [];
        shownIds.current = new Set(items.map((t) => t.id));
        setTrace(items);
      } else {
        // self-heal: queue any steps we missed (e.g. events that raced a reload)
        const queued = new Set(queue.current.map((t) => t.id));
        for (const t of items) if (!shownIds.current.has(t.id) && !queued.has(t.id)) queue.current.push(t);
        queue.current.sort((a, b) => a.id - b.id);
      }
    }
    getJSON<Approval[]>(`/api/approvals?status=pending&incident_id=${i.id}`).then((a) => setPending(a[0] ?? null)).catch(() => {});
  }, []);

  useEffect(() => {
    loadSeries(); loadIncident(); loadNotes();
    getJSON<any>("/api/metrics/latest").then(setLatest).catch(() => {});
    getJSON<User[]>("/api/users").then((u) => { setUsers(u); setUser(u[0]); }).catch(() => {});
  }, [loadSeries, loadIncident, loadNotes]);

  // release queued trace steps at a readable pace
  useEffect(() => {
    const t = setInterval(() => {
      const next = queue.current.shift();
      if (next && !shownIds.current.has(next.id)) {
        shownIds.current.add(next.id);
        setTrace((s) => [...s, next]);
      }
      setNow(Date.now());
    }, STEP_MS);
    return () => clearInterval(t);
  }, []);

  useEffect(() => { document.documentElement.classList.toggle("presenter", presenter); }, [presenter]);

  const onEvent = useCallback((e: RFEvent) => {
    switch (e.type) {
      case "metrics": {
        const s = e.data;
        setLatest(s);
        setSeries((prev) => prev && ({
          ...prev,
          points: [...prev.points, { ts: s.ts, memory_mb: s.memory_mb, healthy: s.healthy ? 1 : 0, version: s.version,
            checkout_error_rate: s.endpoints["/checkout"]?.error_rate, checkout_p95_ms: s.endpoints["/checkout"]?.p95_ms }]
            .filter((x) => x.ts >= s.ts - 300),
        }));
        break;
      }
      case "trace":
        if (e.data.incident_id === incId.current) {
          if (!shownIds.current.has(e.data.id) && !queue.current.some((t) => t.id === e.data.id)) queue.current.push(e.data);
        } else loadIncident();
        break;
      case "approval":
        if (e.data.status === "pending") { setPending(e.data); toast("approval", `Approval needed: ${e.data.summary}`); }
        else setPending(null);
        setVersion((v) => v + 1);
        break;
      case "narration":
        setNarration(e.data.text);
        break;
      case "incident":
        if (e.data.created) toast("alert", `Alert fired: ${e.data.signal} → ${e.data.incident_id} opened`);
        loadIncident();
        break;
      case "ticket":
        if (e.data.to === "Resolved") toast("ok", `${e.data.incident_id} resolved: recovery verified on live metrics`);
        if (e.data.to === "Escalated") toast("warn", `${e.data.incident_id} escalated to the on-call lead`);
        if (e.data.to === "Closed") setNarration(IDLE_TEXT);
        loadIncident();
        setVersion((v) => v + 1);
        break;
      case "notification":
        setNotes((n) => [e.data, ...n.filter((x) => x.id !== e.data.id)]);
        break;
      case "report":
        setVersion((v) => v + 1);
        toast("ok", "Postmortem ready: open the Outcome report tab");
        break;
      case "audit":
        if (tab === "audit") setVersion((v) => v + 1);
        break;
      case "marker":
        loadSeries();
        break;
      case "demo":
        loadSeries(); loadIncident(); loadNotes();
        if (e.data.reset) { setNarration(IDLE_TEXT); setTab(null); setVersion((v) => v + 1); }
        break;
    }
  }, [loadIncident, loadSeries, loadNotes, toast, tab]);
  const conn = useEventStream(onEvent);

  const focusApproval = useCallback(() => {
    document.getElementById("approval-panel")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    reasonRef.current?.focus();
  }, []);

  const runDemo = useCallback(async (path: string, label: string) => {
    try { await postJSON(path); toast("ok", `${label} started`); } catch (err: any) { toast("warn", `${label} failed: ${err.message}`); }
  }, [toast]);

  // keyboard shortcuts (ignored while typing)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName) || e.metaKey || e.ctrlKey || e.altKey) return;
      const k = e.key.toLowerCase();
      if (/^[1-6]$/.test(k)) runDemo(`/api/demo/fault/${k}`, `Scenario ${k}`);
      else if (k === "r") runDemo("/api/demo/reset", "Reset");
      else if (k === "a") { e.preventDefault(); focusApproval(); }
      else if (k === "p") setPresenter((p) => !p);
      else if (k === "o") setTab((t) => (t === "overview" ? null : "overview"));
      else if (k === "h") setOverlay((o) => (o === "how" ? null : "how"));
      else if (e.key === "?") setOverlay((o) => (o === "keys" ? null : "keys"));
      else if (k === "escape") { setTab(null); setDemoOpen(false); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [runDemo, focusApproval]);

  const onStage = (s: string) => {
    setTab(null);
    if (s === "ingest") document.getElementById("ticket")?.scrollIntoView({ behavior: "smooth" });
    if (s === "decide") document.querySelector(".step-decision:last-of-type")?.scrollIntoView({ behavior: "smooth", block: "center" });
    if (s === "act") pending ? focusApproval() : document.querySelector(".step-approval:last-of-type")?.scrollIntoView({ behavior: "smooth", block: "center" });
    if (s === "report") setTab("report");
  };

  const active = inc && inc.status !== "Closed" ? inc : null;
  const lastClosed = inc && inc.status === "Closed" ? inc : null;

  return (
    <div className={`shell ${presenter ? "is-presenter" : ""}`}>
      <header className="header">
        <div className="logo"><Activity size={26} /> RootFix <span className="logo-sub">incident agent</span></div>
        <StageStepper stage={active ? active.stage : null} onClick={onStage} />
        <div className="header-right">
          <label className="approver">
            <span className="xs muted">Approver{user ? ` · ${user.role.replace(/-/g, " ")}` : ""}</span>
            <select value={user?.name ?? ""} onChange={(e) => setUser(users.find((u) => u.name === e.target.value) ?? null)} data-testid="approver">
              {users.map((u) => <option key={u.name} value={u.name}>{u.name}</option>)}
            </select>
          </label>
          <div className={`conn conn-${conn}`} data-testid="conn">
            {conn === "connected" ? <Wifi size={16} /> : <WifiOff size={16} />}
            <span>{conn === "connected" ? "Connected" : conn === "connecting" ? "Connecting…" : "Disconnected"}</span>
            <span className="clock">{conn === "connected" && <>● Live {clock(now / 1000)}</>}</span>
          </div>
          <button className="icon-btn" onClick={() => setOverlay("how")} title="How RootFix works (H)" aria-label="How RootFix works"><Info size={20} /></button>
          <button className="icon-btn" onClick={() => setOverlay("keys")} title="Keyboard shortcuts (?)" aria-label="Keyboard shortcuts"><Keyboard size={20} /></button>
          <button className={`icon-btn ${presenter ? "on" : ""}`} onClick={() => setPresenter((p) => !p)} title="Presenter mode (P)" aria-label="Presenter mode"><MonitorPlay size={20} /></button>
        </div>
      </header>
      {conn === "disconnected" && <div className="banner-disconnected">Live connection lost. Reconnecting… (data shown may be stale)</div>}
      <div className={`narration ${active ? "" : "narration-idle"}`} data-testid="narration">
        <span className="narration-label">{active ? "Now:" : <CheckCircle2 size={18} />}</span> {active ? narration : IDLE_TEXT}
      </div>

      <main className="main">
        <HealthStrip latest={latest} series={series} incidentWindow={inc && inc.status !== "Closed" ? [inc.first_seen, inc.resolved_at ?? inc.escalated_at] : null} />
        <div className="warroom-wrap">
          <div className="warroom">
            <div className="col-left">
              {active ? (
                <>
                  <TicketCard inc={active} onEvidence={setEvidence} onCloseTicket={user?.can_approve ? () =>
                    postJSON(`/api/incidents/${active.id}/close`, { user: user.name, reason: `closed by ${user.name} after review` })
                      .catch((err) => toast("warn", err.message)) : undefined} />
                  <AgentTrace items={trace} onEvidence={setEvidence} />
                </>
              ) : <IdleCard last={lastClosed} />}
            </div>
            <div className="col-right">
              {pending && active ? <ApprovalPanel apr={pending} user={user} onEvidence={setEvidence} focusRef={reasonRef} />
                : active ? <ImpactCard inc={active} /> : <SafetyCard version={version} />}
              <StakeholderFeed items={notes} />
            </div>
          </div>
          {tab && (
            <section className="sheet" data-testid={`sheet-${tab}`}>
              <div className="sheet-head">
                <h2>{TABS.find((t) => t.key === tab)?.label}</h2>
                <button className="icon-btn" onClick={() => setTab(null)} aria-label="Close"><X size={20} /></button>
              </div>
              <div className="sheet-body">
                {tab === "report" && <ReportPanel inc={inc} />}
                {tab === "audit" && <AuditPanel version={version} />}
                {tab === "overview" && <OverviewPanel version={version} />}
                {tab === "history" && <HistoryPanel version={version} />}
              </div>
            </section>
          )}
        </div>
        <nav className="tabbar">
          {TABS.map((t) => (
            <button key={t.key} className={`tab ${tab === t.key ? "tab-on" : ""}`} onClick={() => setTab(tab === t.key ? null : t.key)} data-testid={`tab-${t.key}`}>
              {t.label}{t.key === "report" && inc?.report_md ? " ●" : ""}
            </button>
          ))}
          <span className="spacer" />
          {!presenter && (
            <button className="tab tab-demo" onClick={() => setDemoOpen((o) => !o)} data-testid="demo-toggle"><FlaskConical size={16} /> Demo controls</button>
          )}
          <button className="tab" onClick={() => setOverlay("keys")}><HelpCircle size={16} /> ?</button>
        </nav>
      </main>

      {demoOpen && !presenter && (
        <div className="demo-drawer">
          <DemoControls onDone={(m) => toast("ok", m)} />
          <button className="icon-btn" onClick={() => setDemoOpen(false)} aria-label="Close demo controls"><X size={18} /></button>
        </div>
      )}
      {evidence && <EvidenceDrawer id={evidence} incidentId={inc?.id} onClose={() => setEvidence(null)} />}
      {overlay === "how" && <HowItWorks onClose={() => setOverlay(null)} />}
      {overlay === "keys" && <Shortcuts onClose={() => setOverlay(null)} />}
      <Toasts items={toasts} onDismiss={(id) => setToasts((t) => t.filter((x) => x.id !== id))} />
    </div>
  );
}

function IdleCard({ last }: { last: Incident | null }) {
  const imp = last?.impact_json;
  return (
    <section className="card idle-card" data-testid="idle">
      <div className="idle-head"><CheckCircle2 size={34} /><div><h2>All systems operational</h2>
        <div>RootFix is watching 4 services: checkout, cart, products and the payment gateway.</div></div></div>
      {last && (
        <div className="idle-last">
          <div className="muted small">Last incident</div>
          <div><b>{last.id}</b> · {last.priority} · {last.signal}</div>
          {imp && <div>Resolved in {dur(imp.time_to_resolve_s)} · {inr(imp.rupees_at_risk)} at risk · SLA {imp.sla_resolve_met ? "met ✓" : "missed"}</div>}
        </div>
      )}
      <div className="idle-stages">
        <div className="idle-stage"><b><Database size={16} /> 1. Ingest</b>Alerts, metrics, logs, deploys and past incidents become one ticket.</div>
        <div className="idle-stage"><b><Brain size={16} /> 2. Decide</b>Rule-based priority and SLA; the AI investigates and cites evidence.</div>
        <div className="idle-stage"><b><Wrench size={16} /> 3. Act</b>Least risky fix, only after a named human approves it.</div>
        <div className="idle-stage"><b><FileText size={16} /> 4. Report</b>Verified recovery, ₹ impact, SLA, postmortem and updates.</div>
      </div>
      <div className="idle-hint muted small">Press <kbd>H</kbd> for how RootFix works · <kbd>?</kbd> for shortcuts</div>
    </section>
  );
}

function SafetyCard({ version }: { version: number }) {
  const [chain, setChain] = useState<any>(null);
  const [health, setHealth] = useState<any>(null);
  useEffect(() => {
    getJSON("/api/audit/verify").then(setChain).catch(() => {});
    getJSON("/api/health").then(setHealth).catch(() => {});
  }, [version]);
  const ok = (t: string) => <li><CheckCircle2 size={16} /> {t}</li>;
  return (
    <section className="card safety" data-testid="safety">
      <h3><ShieldCheck size={18} /> Safety controls active</h3>
      <ul>
        {ok("Approval gate in the tool server")}
        {ok("Tool allowlist; no shell access")}
        {ok("Secrets masked in every output")}
        {ok("Prompt-injection detector on logs")}
        {ok("Step, action and time limits")}
        {ok("Auto-rollback if metrics get worse")}
        {chain ? (chain.ok ? ok(`Audit chain verified (${chain.count} entries)`)
          : <li className="bad"><XCircle size={16} /> Audit chain broken at #{chain.broken_at}</li>) : ok("Audit chain: checking…")}
        {ok(`AI model: ${health?.llm_provider ?? "…"} · runtime: ${health?.runtime ?? "…"}`)}
      </ul>
    </section>
  );
}
