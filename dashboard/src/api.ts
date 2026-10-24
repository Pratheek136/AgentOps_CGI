export async function getJSON<T = any>(path: string): Promise<T> {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

export async function postJSON<T = any>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(data?.detail ?? `HTTP ${r.status}`), { status: r.status, data });
  return data;
}

export type MetricPoint = {
  ts: number;
  checkout_error_rate?: number;
  checkout_p95_ms?: number;
  cart_error_rate?: number;
  products_error_rate?: number;
  memory_mb?: number;
  healthy?: number;
  version?: string;
};
export type Marker = { ts: number; kind: string; label: string };
export type Series = { points: MetricPoint[]; markers: Marker[]; thresholds: { error_rate: number; p95_ms: number; memory_mb: number } };
