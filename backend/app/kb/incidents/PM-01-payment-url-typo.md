# PM-01: Checkout outage after payment URL change (INC-0412)

**Priority:** P1 · **Duration:** 9 min · **₹ at risk:** ₹41,300 (synthetic)

**Summary:** A config deploy changed `PAYMENT_API_URL` to a staging host. All checkouts failed with connection refused.
**Root cause:** config change merged without the config validation test running in CI.
**Resolution:** reverted `PAYMENT_API_URL` to the previous deploy's value; verified error rate < 1%.
**What didn't work:** restarting the service (config was re-read, same bad value).
**Follow-ups:** make `test_config.py` a required check; add an allowlist of payment hosts.
