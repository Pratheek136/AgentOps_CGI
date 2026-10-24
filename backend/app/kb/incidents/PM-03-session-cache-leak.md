# PM-03: Memory leak from unbounded session cache (INC-0351)

**Priority:** P3 · **Duration:** 38 min · **₹ at risk:** ₹3,100 (synthetic)

**Summary:** A performance change added a module-level dict that cached per-request data forever. RSS grew ~150 MB/min and latency rose.
**Root cause:** unbounded cache; no eviction.
**Resolution:** a restart helped for 2 minutes, then memory climbed again ("restart only treated the symptom"). Rolled back the release.
**Follow-ups:** require bounded caches (`lru_cache(maxsize=...)`).
