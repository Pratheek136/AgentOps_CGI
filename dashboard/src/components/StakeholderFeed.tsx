import { Megaphone } from "lucide-react";
import { clock } from "../format";

export type Note = { id: number; incident_id: string; ts: number; stage: string; message: string };

export function StakeholderFeed({ items }: { items: Note[] }) {
  return (
    <section className="card feed" data-testid="feed">
      <h3><Megaphone size={18} /> Stakeholder updates</h3>
      {items.length === 0 ? <div className="muted small">No updates sent. Updates go out for P1/P2 incidents at triage, approval and resolution.</div> : (
        <ul className="feed-list">
          {items.map((n) => (
            <li key={n.id} className={`feed-item feed-${n.stage.replace(/\s/g, "-").toLowerCase()}`}>
              <div className="feed-meta"><span className="feed-stage">{n.stage}</span><span>{clock(n.ts)}</span><span>{n.incident_id}</span></div>
              <div>{n.message}</div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
