import { AlertTriangle } from "lucide-react";
import { CartesianGrid, Line, LineChart, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Marker, MetricPoint, Series } from "../api";
import { clock } from "../format";

type ChartDef = { key: keyof MetricPoint; title: string; threshold: number; unit: string; scale?: number; digits: number };

export function HealthCharts({ series, incidentWindow }: { series: Series | null; incidentWindow?: [number, number | null] | null }) {
  if (!series) return <div className="charts">{[0, 1, 2].map((i) => <div key={i} className="chart skeleton" />)}</div>;
  const t = series.thresholds;
  const defs: ChartDef[] = [
    { key: "checkout_error_rate", title: "Checkout error rate", threshold: t.error_rate * 100, unit: "%", scale: 100, digits: 1 },
    { key: "checkout_p95_ms", title: "Checkout p95 latency", threshold: t.p95_ms, unit: "ms", digits: 0 },
    { key: "memory_mb", title: "Shop memory (RSS)", threshold: t.memory_mb, unit: "MB", digits: 0 },
  ];
  return (
    <div className="charts">
      {defs.map((d) => <Chart key={d.key} def={d} points={series.points} markers={series.markers} incidentWindow={incidentWindow} />)}
    </div>
  );
}

function Chart({ def, points, markers, incidentWindow }: { def: ChartDef; points: MetricPoint[]; markers: Marker[]; incidentWindow?: [number, number | null] | null }) {
  const data = points.map((p) => ({ ts: p.ts, v: p[def.key] == null ? null : Number(p[def.key]) * (def.scale ?? 1) }));
  const last = data.length ? data[data.length - 1].v : null;
  const breach = last != null && last > def.threshold;
  const maxV = Math.max(def.threshold * 1.25, ...data.map((d) => d.v ?? 0));
  const x0 = data.length ? data[0].ts : 0;
  const x1 = data.length ? data[data.length - 1].ts : 1;
  return (
    <div className={`chart card ${breach ? "chart-breach" : ""}`}>
      <div className="chart-head">
        <span className="chart-title">{def.title}</span>
        <span className={`chart-value ${breach ? "bad" : ""}`}>
          {breach && <AlertTriangle size={14} />} {last == null ? "—" : `${last.toFixed(def.digits)} ${def.unit}`}
        </span>
      </div>
      <div className="chart-body">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 12, right: 6, left: -12, bottom: 0 }}>
            <CartesianGrid stroke="var(--grid)" vertical={false} />
            <XAxis dataKey="ts" type="number" domain={[x0, x1]} tickFormatter={clock} tick={{ fontSize: 11, fill: "var(--muted)" }} minTickGap={70} stroke="var(--border)" />
            <YAxis domain={[0, Math.ceil(maxV)]} tick={{ fontSize: 11, fill: "var(--muted)" }} width={44} stroke="var(--border)" />
            <Tooltip labelFormatter={(v) => clock(Number(v))} formatter={(v: number) => [`${v?.toFixed(def.digits)} ${def.unit}`, def.title]}
              contentStyle={{ borderRadius: 8, border: "1px solid var(--border)", fontSize: 13 }} />
            {incidentWindow && incidentWindow[0] < x1 && (
              <ReferenceArea x1={Math.max(incidentWindow[0], x0)} x2={incidentWindow[1] ? Math.min(incidentWindow[1], x1) : x1} fill="var(--p1)" fillOpacity={0.08} />
            )}
            <ReferenceLine y={def.threshold} stroke="var(--muted)" strokeDasharray="5 4" />
            {markers.filter((m) => m.ts >= x0).map((m, i) => (
              <ReferenceLine key={i} x={m.ts} stroke={m.kind === "deploy" ? "var(--p2)" : "var(--ok)"} strokeWidth={1.5}
                label={{ value: m.label, position: i % 2 ? "insideBottomLeft" : "insideTopLeft", fontSize: 11, fill: "var(--ink)" }} />
            ))}
            <Line type="monotone" dataKey="v" stroke="var(--series)" strokeWidth={2} dot={false} isAnimationActive={false} connectNulls />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
