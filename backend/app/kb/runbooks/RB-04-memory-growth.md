# RB-04: Memory growth / OOM risk

**Symptoms:** process RSS rises steadily (MB per minute) after a deploy; latency may creep up; eventually the process is killed (OOM).

**Diagnosis**
- `query_metrics memory_mb` over 2-5 minutes: is the slope steady and positive?
- Look for new module-level caches, dicts or lists that grow per request (`git_diff`, `read_file`).

**Remedy**
1. `restart_service` buys time and treats the symptom only. Verify the memory trend after the restart: if it rises again, the cause is in the code.
2. `rollback_deploy` to the release before the leak was introduced.

**Verification:** no rising memory trend for the full window, p95 below threshold.
