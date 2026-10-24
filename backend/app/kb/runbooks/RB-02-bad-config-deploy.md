# RB-02: Bad configuration deploy

**Symptoms:** errors start right after a deploy whose diff only touches `config/`.

**Diagnosis**
- `list_deploys` to find the most recent deploy and its time; correlate with the first bad signal.
- `git_diff <previous tag> <current tag>`: if only config keys changed, it is a config incident.
- Run the config tests (`run_tests`); `test_config.py` validates required keys and endpoints.

**Remedy**
- Prefer `revert_config(key, to_deploy=<last good tag>)`: it is narrower than a full rollback and keeps unrelated changes.
- Only the changed key is reverted; the value must come from the named deploy.
- Secret values (keys, tokens) are masked in diffs. A masked line that changed is still a change.
- If a single-key revert does not restore service, roll back the whole release to the last good deploy instead of reverting keys one at a time.

**Risk:** low. The change is a single key and is instantly reversible.
**Verification:** error rate back below 1% and sustained.
