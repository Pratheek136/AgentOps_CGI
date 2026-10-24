export type Priority = "P1" | "P2" | "P3" | "P4";
export type Sla = {
  priority: Priority; respond_target_min: number; resolve_target_min: number;
  respond_due: number; resolve_due: number; responded_at: number | null;
  respond_met: boolean | null; resolve_met: boolean | null; elapsed_s: number; used_fraction: number; running: boolean;
};
export type Incident = {
  id: string; service: string; endpoints: string[]; alert_rule: string; signal: string;
  first_seen: number; created_at: number; status: string; priority: Priority | null;
  impact: string; urgency: string; priority_reason: string;
  snapshot: any[]; sample_logs: { line: number; text: string; flagged: boolean }[];
  deploy_tag: string | null; deploy_sha: string; prev_tag: string | null;
  kb_matches: { id: string; title: string; score: number }[];
  responded_at: number | null; resolved_at: number | null; closed_at: number | null; escalated_at: number | null;
  history: { ts: number; from_status: string | null; to_status: string; actor: string; reason: string }[];
  sla: Sla; stage: "ingest" | "decide" | "act" | "report";
  verification?: any; impact_json?: any; report_md?: string | null; escalation?: any;
};
export const LIFECYCLE = ["New", "Triaged", "Investigating", "Awaiting approval", "Resolving", "Verifying", "Resolved", "Closed"];
