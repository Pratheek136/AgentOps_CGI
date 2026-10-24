# RB-03: Faulty release: roll back

**Symptoms:** a fraction of requests fail with 500 after a deploy that changed application code (`app/**`). Stack traces point into recently changed functions, e.g. `AttributeError: 'NoneType' object has no attribute ...`.

**Diagnosis**
- Read the traceback in the logs and locate the file and line (`read_file`).
- `git_diff` the previous and current deploy; confirm the failing line was introduced by the diff.
- `run_tests` on the current ref: a failing test that passes on the previous ref confirms a regression.

**Remedy (preferred order)**
1. `rollback_deploy` to the previous good tag. Fast, well understood, fully reversible.
2. Only if a rollback is not acceptable (e.g. it would undo a required change): a minimal code patch (`apply_patch`), with tests passing on a worktree first.

**Rollback plan:** check out the faulty tag again (rolling forward) if the rollback causes new errors.
**Verification:** checkout error rate below 1% for the window.
