import { useState } from "react";
import { postJSON } from "../api";

export const SCENARIOS = [
  { n: 1, title: "Bad config deploy" },
  { n: 2, title: "Faulty release" },
  { n: 3, title: "Memory leak" },
  { n: 4, title: "Payment provider outage" },
  { n: 5, title: "Prompt injection in logs" },
  { n: 6, title: "Hidden second problem" },
];

export function DemoControls({ onDone }: { onDone?: (msg: string) => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const run = async (label: string, path: string) => {
    setBusy(label);
    try {
      const r = await postJSON(path);
      onDone?.(r.deploy ? `${label}: ${r.deploy} deployed` : `${label}: done`);
    } catch (e: any) {
      onDone?.(`${label} failed: ${e.message}`);
    } finally {
      setBusy(null);
    }
  };
  return (
    <div className="demo-controls">
      <div className="demo-label">Demo only</div>
      {SCENARIOS.map((s) => (
        <button key={s.n} className="btn btn-ghost" disabled={!!busy} onClick={() => run(`Scenario ${s.n}`, `/api/demo/fault/${s.n}`)}>
          {s.n}. {s.title}
        </button>
      ))}
      <button className="btn btn-ghost" disabled={!!busy} onClick={() => run("Reset", "/api/demo/reset")}>Reset</button>
      {busy && <span className="muted">{busy}…</span>}
    </div>
  );
}
