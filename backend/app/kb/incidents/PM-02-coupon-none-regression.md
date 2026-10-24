# PM-02: Partial checkout failures from coupon regression (INC-0388)

**Priority:** P2 · **Duration:** 14 min · **₹ at risk:** ₹22,900 (synthetic)

**Summary:** A release changed discount handling; orders without a coupon crashed with `AttributeError: 'NoneType' object has no attribute 'percent'`. About a third of checkouts failed.
**Root cause:** the new code dereferenced `coupon` before the `None` check.
**Resolution:** rolled back to the previous deploy; a fixed version shipped the next day with a test for coupon-less orders.
**Follow-ups:** keep the "checkout without coupon" test mandatory.
