import { Check, Database, Brain, Wrench, FileText } from "lucide-react";

const STAGES = [
  { key: "ingest", label: "Ingest", Icon: Database },
  { key: "decide", label: "Decide", Icon: Brain },
  { key: "act", label: "Act", Icon: Wrench },
  { key: "report", label: "Report", Icon: FileText },
] as const;

export function StageStepper({ stage, onClick }: { stage: string | null; onClick?: (s: string) => void }) {
  const idx = stage ? STAGES.findIndex((s) => s.key === stage) : -1;
  return (
    <nav className="stepper" aria-label="Incident stage" data-testid="stepper">
      {STAGES.map((s, i) => {
        const state = idx < 0 ? "idle" : i < idx || (i === idx && stage === "report") ? "done" : i === idx ? "current" : "todo";
        return (
          <button key={s.key} className={`stage stage-${state}`} onClick={() => onClick?.(s.key)}
            aria-current={state === "current" ? "step" : undefined}>
            <span className="stage-icon">{state === "done" ? <Check size={16} /> : <s.Icon size={16} />}</span>
            {s.label}
            {i < STAGES.length - 1 && <span className="stage-arrow">→</span>}
          </button>
        );
      })}
    </nav>
  );
}
