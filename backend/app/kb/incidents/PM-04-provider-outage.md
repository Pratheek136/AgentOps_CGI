# PM-04: Payment provider outage (INC-0297)

**Priority:** P1 · **Duration:** 47 min · **₹ at risk:** ₹96,800 (synthetic)

**Summary:** The external payment provider returned 503 for all charges. No deploy had happened in 2 days.
**Root cause:** provider-side incident.
**Resolution:** escalated to the on-call lead, who engaged the provider; stakeholder updates every 15 minutes. No changes were made to our systems.
**What didn't work:** an engineer's rollback attempt changed nothing and added risk.
**Follow-ups:** add provider status page check to the runbook; consider a secondary provider.
