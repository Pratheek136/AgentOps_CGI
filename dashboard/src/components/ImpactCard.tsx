import { useEffect, useRef, useState } from "react";
import { CheckCircle2, IndianRupee, Siren, XCircle } from "lucide-react";
import { getJSON } from "../api";
import type { Incident } from "../types";
import { dur, inr, pct } from "../format";

function useCountUp(target: number, ms = 900) {
  const [v, setV] = useState(target);
  const from = useRef(target);
  useEffect(() => {
    const start = performance.now(), a = from.current, b = target;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) { setV(b); from.current = b; return; }
    let raf = 0;
    const step = (now: number) => {
      const k = Math.min(1, (now - start) / ms);
      setV(a + (b - a) * k);
      if (k < 1) raf = requestAnimationFrame(step); else from.current = b;
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [target, ms]);
  return v;
}

export function ImpactCard({ inc }: { inc: Incident }) {
  const [imp, setImp] = useState<any>(null);
  useEffect(() => {
    let alive = true;
    const load = () => getJSON(`/api/incidents/${inc.id}/impact`).then((d) => alive && setImp(d)).catch(() => {});
    load();
    const t = inc.sla.running ? setInterval(load, 2000) : undefined;
    return () => { alive = false; if (t) clearInterval(t); };
  }, [inc.id, inc.sla.running, inc.status]);
  const rupees = useCountUp(imp?.rupees_at_risk ?? 0);
  if (!imp) return <div className="card impact skeleton" style={{ height: 190 }} />;
  const live = !imp.final;
  return (
    <section className="card impact" data-testid="impact">
      <div className="impact-head">
        <h3>{live ? "Live business impact" : "Business impact"}</h3>
        <span className="muted xs">{imp.label}</span>
      </div>
      <div className="impact-hero">
        <IndianRupee size={22} />
        <span className="hero-num">{inr(rupees).slice(1)}</span>
        <span className="hero-label">orders at risk</span>
      </div>
      <div className="impact-grid">
        <div><span className="kpi">{imp.failed_checkouts}</span><span className="kpi-label">failed checkouts</span></div>
        <div><span className="kpi">{imp.disruption_minutes.toFixed(1)}</span><span className="kpi-label">minutes of disruption</span></div>
        <div><span className="kpi">{pct(imp.affected_share)}</span><span className="kpi-label">of checkouts affected</span></div>
      </div>
      {!live && (imp.escalated && !inc.resolved_at ? (
        <div className="sla-final sla-escalated"><Siren size={18} /> Escalated to on-call; {dur(imp.window_end - inc.created_at)} after the alert</div>
      ) : imp.sla_resolve_met ? (
        <div className="sla-final sla-met" data-testid="sla-final"><CheckCircle2 size={18} /> SLA met: resolved in {dur(imp.time_to_resolve_s)} vs {imp.sla_resolve_target_min}m target</div>
      ) : (
        <div className="sla-final sla-missed" data-testid="sla-final"><XCircle size={18} /> SLA missed: resolved in {dur(imp.time_to_resolve_s)} vs {imp.sla_resolve_target_min}m target</div>
      ))}
    </section>
  );
}
