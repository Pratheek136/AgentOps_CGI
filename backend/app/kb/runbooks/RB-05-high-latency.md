# RB-05: High latency on the checkout path

**Symptoms:** checkout p95 above 1,500 ms, error rate may be normal.

**Diagnosis**
- Is latency dominated by the payment call? Check `PAYMENT_TIMEOUT_MS` and payment error types.
- Did a deploy add per-request work (loops over caches, extra I/O)?
- Correlate with memory growth (RB-04) and pool size (RB-06).

**Remedy:** revert the change that introduced the extra work (config revert or rollback). Restart only if resource exhaustion is shown.
**Verification:** p95 below threshold for the window.
