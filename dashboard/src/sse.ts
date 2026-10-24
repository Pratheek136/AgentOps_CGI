import { useEffect, useRef, useState } from "react";

export type RFEvent = { id: number; type: string; ts: number; data: any };
export type ConnState = "connecting" | "connected" | "disconnected";

/** Subscribes to /api/events; auto-reconnects (EventSource retry + manual fallback). */
export function useEventStream(onEvent: (e: RFEvent) => void): ConnState {
  const [state, setState] = useState<ConnState>("connecting");
  const handler = useRef(onEvent);
  handler.current = onEvent;

  useEffect(() => {
    let es: EventSource | null = null;
    let retry: number | undefined;
    let closed = false;

    const open = () => {
      es = new EventSource("/api/events");
      es.onopen = () => setState("connected");
      es.onerror = () => {
        setState("disconnected");
        if (es && es.readyState === EventSource.CLOSED && !closed) {
          retry = window.setTimeout(open, 2000);
        }
      };
      es.onmessage = (m) => handler.current(JSON.parse(m.data));
      // named events: forward everything through one handler
      const forward = (m: MessageEvent) => handler.current(JSON.parse(m.data));
      for (const t of KNOWN_TYPES) es.addEventListener(t, forward as EventListener);
    };
    open();
    return () => {
      closed = true;
      if (retry) clearTimeout(retry);
      es?.close();
    };
  }, []);

  return state;
}

export const KNOWN_TYPES = [
  "hello", "system", "metrics", "incident", "ticket", "trace", "approval",
  "audit", "notification", "narration", "marker", "report", "demo",
];
