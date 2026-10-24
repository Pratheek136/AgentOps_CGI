# RB-07: Unknown cause / external dependency: escalate

**When to use:** no recent deploy or config change explains the incident, or the failing component is outside our control (e.g. the payment provider returns `503 Service Unavailable`).

**Signs of an external outage**
- Errors are 503 from the provider, not connection refused.
- `list_deploys` shows no deploy close to the first bad signal.
- Rolling back would change nothing because our code and config did not change.

**What to do**
- Do not make speculative changes to production. A rollback or restart cannot fix a provider outage and adds risk.
- `escalate` with a structured summary: symptoms, evidence, what was ruled out, business impact so far.
- Notify stakeholders; the payment provider's status page and support line are the next step for the on-call lead.
