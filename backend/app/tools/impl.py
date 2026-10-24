"""Tool implementations. Services are touched only through the ServiceRuntime;
git through GitPython. No shell, no eval."""
from __future__ import annotations

import difflib
import re
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from git import GitCommandError

from .. import audit, db, gitinfo, logsource, retrieval, tickets
from ..config import paths, thresholds
from ..deploys import add_marker, make_deploy
from ..events import bus
from ..runtime import TestRun, get_shop_runtime
from .registry import ValidationError, patch_files_and_size, read_config_at

MAX_DIFF_CHARS = 6000


# ---------------------------------------------------------------- read tools
def get_incident(incident_id: str) -> tuple[str, dict]:
    inc = tickets.view(incident_id)
    snap = inc["snapshot"] or []
    last = snap[-1] if snap else {}
    data = {
        "id": inc["id"], "status": inc["status"], "priority": inc["priority"], "signal": inc["signal"],
        "alert_rule": inc["alert_rule"], "service": inc["service"], "endpoints": inc["endpoints"],
        "first_seen": _iso(inc["first_seen"]), "current_deploy": inc["deploy_tag"], "current_sha": inc["deploy_sha"],
        "previous_deploy": inc["prev_tag"], "latest_metrics": last,
        "kb_matches": [f"KB:{m['id']} {m['title']}" for m in inc["kb_matches"]],
    }
    lines = [f"{k}: {v}" for k, v in data.items()]
    lines.append("sample error logs:")
    lines += [f"  {s['text']}" for s in inc["sample_logs"][:3]]
    return "\n".join(lines), data


def query_metrics(metric: str, endpoint: str, window_s: int) -> tuple[str, dict]:
    since = time.time() - window_s
    ep = "_service" if metric == "memory_mb" else endpoint
    rows = db.query(f"SELECT ts, {metric} AS v FROM metrics WHERE endpoint = ? AND ts >= ? ORDER BY ts", (ep, since))
    vals = [r for r in rows if r["v"] is not None]
    if not vals:
        return f"no {metric} data for {endpoint} in the last {window_s}s", {"points": []}
    step = max(1, len(vals) // 30)
    pts = vals[::step]
    nums = [r["v"] for r in vals]
    stats = {"min": round(min(nums), 4), "max": round(max(nums), 4), "latest": round(nums[-1], 4),
             "samples": len(nums)}
    if metric == "memory_mb":
        from ..alerts import memory_slope_mb_per_min
        stats["slope_mb_per_min"] = round(memory_slope_mb_per_min([(r["ts"], r["v"]) for r in vals[-30:]]), 1)
    lines = [f"{metric} for {endpoint if ep != '_service' else 'shop process'} over {window_s}s: {stats}"]
    lines += [f"  {_iso(r['ts'])}  {round(r['v'], 4)}" for r in pts]
    return "\n".join(lines), {"stats": stats, "points": [(round(r["ts"], 1), r["v"]) for r in pts]}


def read_logs(since_s: int, level: str | None, contains: str | None, limit: int) -> tuple[str, dict]:
    recs = logsource.read(since_s=since_s, level=level, contains=contains, limit=limit)
    if not recs:
        return "no matching log records", {"count": 0}
    # collapse identical errors so the model sees variety, keep line ids
    lines = [logsource.format_record(r, with_traceback=i >= len(recs) - 3) for i, r in enumerate(recs)]
    return "\n".join(lines), {"count": len(recs), "lines": [r["line"] for r in recs]}


def list_deploys(n: int) -> tuple[str, list]:
    deps = gitinfo.list_deploys(n)
    cur = gitinfo.current_deploy()
    lines = [f"{d['tag']}  {d['sha']}  {d['time']}  {d['message']}  files={d['files_changed']}"
             + ("   <- running" if d["tag"] == cur["tag"] else "") for d in deps]
    return "\n".join(lines), deps


def git_diff(from_ref: str, to_ref: str) -> tuple[str, dict]:
    diff = gitinfo.repo().git.diff(from_ref, to_ref)
    truncated = len(diff) > MAX_DIFF_CHARS
    text = diff[:MAX_DIFF_CHARS] + ("\n… (truncated)" if truncated else "")
    return text or "(no differences)", {"from": from_ref, "to": to_ref, "truncated": truncated}


def read_file(path: str, start: int, end: int) -> tuple[str, dict]:
    lines = (paths.shop_repo / path).read_text(encoding="utf-8").splitlines()
    chunk = lines[start - 1:end]
    text = "\n".join(f"{i:4d}  {l}" for i, l in enumerate(chunk, start=start))
    return f"{path} lines {start}-{start + len(chunk) - 1} of {len(lines)}\n{text}", {"path": path, "total": len(lines)}


def search_knowledge_base(query: str, k: int) -> tuple[str, list]:
    res = retrieval.search(query, k)
    lines = [f"KB:{r['id']} ({r['kind']}, score {r['score']}): {r['title']}\n  {r['snippet']}" for r in res]
    return "\n".join(lines), res


@contextmanager
def worktree(ref: str) -> Iterator[Path]:
    repo = gitinfo.repo()
    wt = paths.data / "worktrees" / f"wt-{uuid.uuid4().hex[:8]}"
    wt.parent.mkdir(parents=True, exist_ok=True)
    repo.git.worktree("add", "--detach", str(wt), ref)
    try:
        yield wt
    finally:
        try:
            repo.git.worktree("remove", "--force", str(wt))
        except GitCommandError:
            pass


def run_tests(ref: str) -> tuple[str, dict]:
    with worktree(ref) as wt:
        res = get_shop_runtime().run_tests(wt)
    return _test_text(ref, res), _test_data(res)


def _test_text(ref: str, res: TestRun) -> str:
    out = res.output.strip()
    return f"tests at {ref}: {'PASSED' if res.passed else 'FAILED'}: {res.summary} ({res.duration_s}s)\n{out[-2500:]}"


def _test_data(res: TestRun) -> dict:
    return {"passed": res.passed, "summary": res.summary, "duration_s": res.duration_s}


def check_patch(diff: str) -> tuple[bool, str, TestRun | None]:
    """Apply the patch on a worktree at HEAD and run tests. Returns (applies, message, tests)."""
    with worktree("HEAD") as wt:
        patch_file = wt / ".rootfix.patch"
        patch_file.write_text(diff, encoding="utf-8")
        repo = gitinfo.repo()
        try:
            repo.git.execute(["git", "-C", str(wt), "apply", "--recount", "--whitespace=nowarn", str(patch_file)])
        except GitCommandError as exc:
            return False, f"patch does not apply cleanly: {exc.stderr.strip()[:400]}", None
        patch_file.unlink()
        res = get_shop_runtime().run_tests(wt)
        return True, res.summary, res


# ---------------------------------------------------------------- mutating tools
def _ensure_clean() -> None:
    repo = gitinfo.repo()
    if repo.is_dirty(untracked_files=False):
        repo.git.checkout("--", ".")  # discard stray edits: production must match a commit


def restart_service(incident_id: str) -> tuple[str, dict]:
    st = get_shop_runtime().restart()
    return f"shop restarted: running={st.running} healthy={st.healthy} pid={st.pid}", st.__dict__


def revert_config(incident_id: str, key: str, to_deploy: str) -> tuple[str, dict]:
    _ensure_clean()
    cfg_path = paths.shop_repo / "config" / "app.env"
    old_value = read_config_at(to_deploy)[key]
    text = cfg_path.read_text(encoding="utf-8")
    new_text = re.sub(rf"^{re.escape(key)}=.*$", lambda _m: f"{key}={old_value}", text, flags=re.M)
    tag = make_deploy(f"revert {key} to value from {to_deploy} ({incident_id})", {"config/app.env": new_text})
    st = get_shop_runtime().restart()
    return f"{key} reverted to the {to_deploy} value; deployed as {tag}; shop healthy={st.healthy}", \
        {"deploy": tag, "healthy": st.healthy}


def rollback_deploy(incident_id: str, to_tag: str) -> tuple[str, dict]:
    _ensure_clean()
    before = gitinfo.current_deploy()
    gitinfo.repo().git.checkout(to_tag)  # detached HEAD at the good deploy
    st = get_shop_runtime().restart()
    return f"rolled back from {before['tag']} to {to_tag}; shop healthy={st.healthy}", \
        {"from": before["tag"], "to": to_tag, "healthy": st.healthy}


def apply_patch(incident_id: str, unified_diff: str) -> tuple[str, dict]:
    _ensure_clean()
    applies, msg, tests = check_patch(unified_diff)
    if not applies or tests is None or not tests.passed:
        raise ValidationError(f"patch re-validation failed: {msg}")
    repo = gitinfo.repo()
    if repo.head.is_detached:
        repo.git.checkout("-B", "main")
    patch_file = paths.data / f"patch-{uuid.uuid4().hex[:6]}.diff"
    patch_file.write_text(unified_diff, encoding="utf-8")
    try:
        repo.git.apply("--recount", "--whitespace=nowarn", str(patch_file))
    finally:
        patch_file.unlink(missing_ok=True)
    files, _ = patch_files_and_size(unified_diff)
    contents = {f: (paths.shop_repo / f).read_text(encoding="utf-8") for f in files}
    tag = make_deploy(f"hotfix ({incident_id}): agent patch, tests passed", contents)
    st = get_shop_runtime().restart()
    return f"patch applied and deployed as {tag}; tests: {tests.summary}; shop healthy={st.healthy}", \
        {"deploy": tag, "healthy": st.healthy}


def escalate(incident_id: str, reason: str, summary: str) -> tuple[str, dict]:
    db.execute("UPDATE incidents SET escalation = ? WHERE id = ?",
               (db.dumps({"reason": reason, "summary": summary}), incident_id))
    inc = tickets.get(incident_id)
    if inc and inc["status"] != tickets.ESCALATED:
        tickets.set_status(incident_id, tickets.ESCALATED, actor="agent", reason=reason)
    bus.publish("incident", {"incident_id": incident_id, "escalated": True})
    return f"escalated to on-call: {reason}", {"reason": reason}


# ---------------------------------------------------------------- approval previews
def preview(tool: str, args: dict) -> dict:
    """Deterministic diff preview, plain-words summary and rollback plan for an approval."""
    cur = gitinfo.current_deploy()
    cur_label = cur["tag"] or cur["sha"]
    if tool == "revert_config":
        text = (paths.shop_repo / "config" / "app.env").read_text(encoding="utf-8")
        old = read_config_at(args["to_deploy"])[args["key"]]
        new = re.sub(rf"^{re.escape(args['key'])}=.*$", lambda _m: f"{args['key']}={old}", text, flags=re.M)
        diff = "".join(difflib.unified_diff(text.splitlines(True), new.splitlines(True),
                                            "a/config/app.env", "b/config/app.env"))
        return {"diff": diff, "risk": "low",
                "summary": f"Revert {args['key']} to its {args['to_deploy']} value and restart checkout",
                "rollback_plan": f"Roll back to {cur_label} (re-applies the current value) and restart."}
    if tool == "rollback_deploy":
        diff = gitinfo.repo().git.diff("HEAD", args["to_tag"])[:MAX_DIFF_CHARS]
        return {"diff": diff, "risk": "medium",
                "summary": f"Roll back the shop from {cur_label} to {args['to_tag']}",
                "rollback_plan": f"Roll forward: check out {cur_label} again and restart."}
    if tool == "apply_patch":
        return {"diff": args["unified_diff"], "risk": "high",
                "summary": f"Apply a code patch on top of {cur_label} (tests passed on a worktree)",
                "rollback_plan": f"Roll back to {cur_label} (pre-patch) and restart."}
    if tool == "restart_service":
        return {"diff": "", "risk": "low", "summary": "Restart the shop process",
                "rollback_plan": "No code or config change; nothing to roll back."}
    return {"diff": "", "risk": "unknown", "summary": tool, "rollback_plan": ""}


def _iso(ts: float | None) -> str:
    if not ts:
        return ""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts))


READ_IMPLS = {
    "get_incident": lambda inc, a: get_incident(inc),
    "query_metrics": lambda inc, a: query_metrics(**a),
    "read_logs": lambda inc, a: read_logs(**a),
    "list_deploys": lambda inc, a: list_deploys(**a),
    "git_diff": lambda inc, a: git_diff(**a),
    "read_file": lambda inc, a: read_file(**a),
    "search_knowledge_base": lambda inc, a: search_knowledge_base(**a),
    "run_tests": lambda inc, a: run_tests(**a),
    "escalate": lambda inc, a: escalate(inc, **a),
}
MUTATING_IMPLS = {
    "restart_service": lambda inc, a: restart_service(inc),
    "revert_config": lambda inc, a: revert_config(inc, **a),
    "rollback_deploy": lambda inc, a: rollback_deploy(inc, **a),
    "apply_patch": lambda inc, a: apply_patch(inc, **a),
}


def restore_ref(incident_id: str, ref: str) -> None:
    """System auto-rollback to the pre-change version (the approved rollback plan)."""
    _ensure_clean()
    gitinfo.repo().git.checkout(ref)
    get_shop_runtime().restart()
    add_marker("action", f"auto-rollback → {ref}", incident_id)
