# RB-01: Payment gateway connection failures

**Symptoms:** `/checkout` returns 502; logs show `ConnectionError: Connection refused: could not connect to payment gateway`. Error rate is near 100% and starts abruptly.

**Likely causes**
1. `PAYMENT_API_URL` in `config/app.env` changed in a recent deploy (wrong host or port).
2. Network policy or DNS change for the payment host.
3. The payment provider itself is down (that returns 503 errors, not connection refused; see RB-07).

**Diagnosis**
- Compare `config/app.env` between the current and previous deploy (`git_diff`).
- Check that the configured host is the internal gateway `payments.internal:9000`.
- Confirm the error type in the logs: connection refused means our side, 503 means the provider.

**Remedy (least risky first)**
1. Revert the `PAYMENT_API_URL` key to the value from the last good deploy (`revert_config`).
2. If the revert does not restore service (e.g. errors change to `401 Unauthorized`), the release changed more than one thing: roll back the whole release to the last good deploy (`rollback_deploy`). Do not keep reverting keys one by one.

**Verification:** checkout error rate below 1% for the full verification window.
**Rollback plan:** re-apply the reverted value, or check out the previous deploy tag.
