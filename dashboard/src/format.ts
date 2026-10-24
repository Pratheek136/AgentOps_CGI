export const inr = (v: number | null | undefined) => {
  if (v == null) return "—";
  const n = Math.round(v);
  const s = Math.abs(n).toString();
  let out = s;
  if (s.length > 3) {
    let head = s.slice(0, -3);
    const tail = s.slice(-3);
    const groups: string[] = [];
    while (head.length > 2) { groups.unshift(head.slice(-2)); head = head.slice(0, -2); }
    if (head) groups.unshift(head);
    out = `${groups.join(",")},${tail}`;
  }
  return `${n < 0 ? "-" : ""}₹${out}`;
};
export const pct = (v: number | null | undefined, d = 0) => (v == null ? "—" : `${(v * 100).toFixed(d)}%`);
export const dur = (s: number | null | undefined) => {
  if (s == null) return "—";
  s = Math.max(0, Math.round(s));
  return s >= 60 ? `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s` : `${s}s`;
};
export const clock = (ts: number) => new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
