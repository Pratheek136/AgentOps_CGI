import { AlertTriangle, CheckCircle2, CreditCard, Package, ShoppingCart, XCircle } from "lucide-react";
import { HealthCharts } from "./HealthCharts";
import type { Series } from "../api";
import { pct } from "../format";

type Tile = { name: string; Icon: any; state: "ok" | "degraded" | "failing"; detail: string };

function epState(rate: number | undefined, p95?: number): Tile["state"] {
  if (rate == null) return "ok";
  if (rate >= 0.05 || (p95 ?? 0) > 1500) return "failing";
  if (rate >= 0.01) return "degraded";
  return "ok";
}

export function tilesFrom(latest: any): Tile[] {
  const ep = latest?.endpoints ?? {};
  const c = ep["/checkout"], cart = ep["/cart"], prod = ep["/products"];
  const pay = latest?.payment;
  const payRate = pay && pay.checks ? pay.errors / pay.checks : 0;
  const down = latest && !latest.healthy;
  const mk = (name: string, Icon: any, m: any): Tile => {
    const state = down ? "failing" : epState(m?.error_rate, m?.p95_ms);
    const detail = down ? "Not responding" : state === "ok" ? `OK · p95 ${Math.round(m?.p95_ms ?? 0)} ms` : `${pct(m?.error_rate)} failing`;
    return { name, Icon, state, detail };
  };
  return [
    mk("Checkout", ShoppingCart, c),
    mk("Cart", ShoppingCart, cart),
    mk("Products", Package, prod),
    { name: "Payment gateway", Icon: CreditCard, state: payRate >= 0.05 ? "failing" : payRate > 0 ? "degraded" : "ok",
      detail: payRate >= 0.05 ? `${pct(payRate)} of charges failing` : "OK" },
  ];
}

const STATE_ICON = { ok: CheckCircle2, degraded: AlertTriangle, failing: XCircle };
const STATE_LABEL = { ok: "Healthy", degraded: "Degraded", failing: "Failing" };

export function HealthStrip({ latest, series, incidentWindow }: { latest: any; series: Series | null; incidentWindow: [number, number | null] | null }) {
  const tiles = tilesFrom(latest);
  return (
    <section className="health" id="health" aria-label="Service health">
      <div className="tiles" data-testid="tiles">
        {tiles.map((t) => {
          const S = STATE_ICON[t.state];
          return (
            <div key={t.name} className={`tile tile-${t.state}`}>
              <div className="tile-name"><t.Icon size={16} /> {t.name}</div>
              <div className="tile-state"><S size={16} /> {STATE_LABEL[t.state]}</div>
              <div className="tile-detail">{t.detail}</div>
            </div>
          );
        })}
      </div>
      <HealthCharts series={series} incidentWindow={incidentWindow} />
    </section>
  );
}
