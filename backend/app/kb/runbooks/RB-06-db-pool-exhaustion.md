# RB-06: Database connection pool exhaustion

**Symptoms:** timeouts acquiring connections, latency spikes under load, errors such as `PoolTimeout`.

**Diagnosis:** check `DB_POOL_SIZE` in `config/app.env` against previous deploys; compare traffic level.

**Remedy:** revert `DB_POOL_SIZE` to the last good value (`revert_config`). Do not raise it above 50 without capacity review.
**Verification:** latency and error rate back to baseline.
