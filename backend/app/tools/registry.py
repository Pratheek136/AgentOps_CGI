"""Tool definitions: risk tier, JSON schema, argument validators. The only tools the agent has."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from git import GitCommandError

from .. import gitinfo
from ..config import paths

READ, LOW, GATED = "read", "low", "gated"

MAX_PATCH_LINES = 30
MAX_READ_LINES = 200
METRICS = {"error_rate", "p95_ms", "p50_ms", "memory_mb", "requests"}
ENDPOINTS = {"/checkout", "/cart", "/products"}


class ValidationError(Exception):
    pass


@dataclass
class ToolSpec:
    name: str
    tier: str
    description: str
    parameters: dict
    validate: Callable[[dict], dict] = field(default=lambda a: a)

    @property
    def mutating(self) -> bool:
        return self.tier in (LOW, GATED)


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or []}


# ---------------------------------------------------------------- validators
def _int_range(args: dict, key: str, lo: int, hi: int, default: int) -> int:
    v = args.get(key, default)
    try:
        v = int(v)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{key} must be an integer") from exc
    if not lo <= v <= hi:
        raise ValidationError(f"{key} must be between {lo} and {hi}")
    return v


def _known_ref(ref: str) -> str:
    if not isinstance(ref, str) or not re.fullmatch(r"[A-Za-z0-9._\-]{1,64}", ref):
        raise ValidationError(f"invalid ref {ref!r}")
    try:
        gitinfo.repo().commit(ref)
    except (GitCommandError, ValueError, Exception) as exc:  # noqa: BLE001
        raise ValidationError(f"unknown git ref {ref!r}") from exc
    return ref


def _deploy_tag(tag: Any) -> str:
    if not isinstance(tag, str) or not gitinfo.DEPLOY_RE.fullmatch(tag):
        raise ValidationError(f"{tag!r} is not a deploy tag (expected deploy-N)")
    if tag not in gitinfo.deploy_tags():
        raise ValidationError(f"deploy tag {tag} does not exist")
    return tag


def v_query_metrics(a: dict) -> dict:
    metric = a.get("metric")
    if metric not in METRICS:
        raise ValidationError(f"metric must be one of {sorted(METRICS)}")
    ep = a.get("endpoint") or "/checkout"
    if ep not in ENDPOINTS:
        raise ValidationError(f"endpoint must be one of {sorted(ENDPOINTS)}")
    return {"metric": metric, "endpoint": ep, "window_s": _int_range(a, "window_s", 10, 3600, 300)}


def v_read_logs(a: dict) -> dict:
    level = a.get("level")
    if level is not None and str(level).upper() not in {"INFO", "WARNING", "ERROR"}:
        raise ValidationError("level must be INFO, WARNING or ERROR")
    contains = a.get("contains")
    if contains is not None and (not isinstance(contains, str) or len(contains) > 200):
        raise ValidationError("contains must be a string ≤ 200 chars")
    return {"since_s": _int_range(a, "since_s", 1, 3600, 300), "level": level.upper() if level else None,
            "contains": contains or None, "limit": _int_range(a, "limit", 1, 200, 50)}


def v_list_deploys(a: dict) -> dict:
    return {"n": _int_range(a, "n", 1, 20, 5)}


def v_git_diff(a: dict) -> dict:
    return {"from_ref": _known_ref(a.get("from_ref")), "to_ref": _known_ref(a.get("to_ref", "HEAD"))}


def safe_repo_path(path: Any) -> Path:
    if not isinstance(path, str) or not path or "\x00" in path:
        raise ValidationError("path must be a non-empty string")
    p = PurePosixPath(path.replace("\\", "/"))
    if p.is_absolute() or ".." in p.parts or (p.parts and p.parts[0] == ".git"):
        raise ValidationError(f"path {path!r} is outside shop_repo")
    full = (paths.shop_repo / p).resolve()
    root = paths.shop_repo.resolve()
    if root not in full.parents and full != root:
        raise ValidationError(f"path {path!r} is outside shop_repo")
    return full


def v_read_file(a: dict) -> dict:
    full = safe_repo_path(a.get("path"))
    if not full.is_file():
        raise ValidationError(f"no such file {a.get('path')!r}")
    start = _int_range(a, "start", 1, 100000, 1)
    end = _int_range(a, "end", start, 100000, start + MAX_READ_LINES - 1)
    if end - start + 1 > MAX_READ_LINES:
        raise ValidationError(f"at most {MAX_READ_LINES} lines per read")
    return {"path": full.relative_to(paths.shop_repo.resolve()).as_posix(), "start": start, "end": end}


def v_search_kb(a: dict) -> dict:
    q = a.get("query")
    if not isinstance(q, str) or not q.strip() or len(q) > 500:
        raise ValidationError("query must be a non-empty string ≤ 500 chars")
    return {"query": q.strip(), "k": _int_range(a, "k", 1, 5, 3)}


def v_run_tests(a: dict) -> dict:
    ref = a.get("ref") or "HEAD"
    return {"ref": _known_ref(ref)}


def v_record_decision(a: dict) -> dict:
    hyps = a.get("hypotheses")
    if not isinstance(hyps, list) or not hyps:
        raise ValidationError("hypotheses must be a non-empty list")
    clean = []
    for h in hyps[:5]:
        if not isinstance(h, dict) or not isinstance(h.get("cause"), str):
            raise ValidationError("each hypothesis needs a 'cause' string")
        try:
            conf = float(h.get("confidence"))
        except (TypeError, ValueError) as exc:
            raise ValidationError("confidence must be a number 0-1") from exc
        if not 0 <= conf <= 1:
            raise ValidationError("confidence must be between 0 and 1")
        ev = h.get("evidence") or []
        if not isinstance(ev, list) or not all(isinstance(e, str) for e in ev):
            raise ValidationError("evidence must be a list of ids")
        clean.append({"cause": h["cause"][:300], "confidence": conf, "evidence": ev[:10]})
    if not any(h["evidence"] for h in clean):
        raise ValidationError("a decision must cite evidence ids (tool result ids like tr-3, log#41, or KB ids like KB:RB-01)")
    action = a.get("chosen_action")
    if action not in ACTION_TOOLS | {"escalate", "none"}:
        raise ValidationError(f"chosen_action must be one of {sorted(ACTION_TOOLS | {'escalate', 'none'})}")
    rationale = str(a.get("rationale") or "").strip()
    if not rationale:
        raise ValidationError("rationale is required")
    return {"hypotheses": sorted(clean, key=lambda h: -h["confidence"]), "chosen_action": action,
            "rationale": rationale[:600], "expected_effect": str(a.get("expected_effect") or "")[:300],
            "risk": str(a.get("risk") or "")[:300]}


def v_restart(a: dict) -> dict:
    return {}


def read_config_at(ref: str) -> dict[str, str]:
    text = gitinfo.repo().git.show(f"{ref}:config/app.env")
    out = {}
    for line in text.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def v_revert_config(a: dict) -> dict:
    key = a.get("key")
    if not isinstance(key, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", key):
        raise ValidationError("key must be an UPPER_SNAKE config key")
    to = _deploy_tag(a.get("to_deploy"))
    current = read_config_at("HEAD")
    if key not in current:
        raise ValidationError(f"key {key} does not exist in the current config")
    old = read_config_at(to)
    if key not in old:
        raise ValidationError(f"key {key} does not exist in {to}")
    if old[key] == current[key]:
        raise ValidationError(f"{key} already has the value from {to}")
    return {"key": key, "to_deploy": to}


def v_rollback(a: dict) -> dict:
    tag = _deploy_tag(a.get("to_tag"))
    r = gitinfo.repo()
    head = r.head.commit
    target = r.tags[tag].commit
    if target.hexsha == head.hexsha:
        raise ValidationError(f"{tag} is already the running version")
    if not r.is_ancestor(target, head):
        raise ValidationError(f"{tag} is not an ancestor of the running version")
    return {"to_tag": tag}


_DIFF_FILE = re.compile(r"^(?:---|\+\+\+) (?:[ab]/)?(\S+)")


def patch_files_and_size(diff: str) -> tuple[set[str], int]:
    files, changed = set(), 0
    for line in diff.splitlines():
        if line.startswith(("--- ", "+++ ")):
            m = _DIFF_FILE.match(line)
            if m and m.group(1) != "/dev/null":
                files.add(m.group(1))
        elif line.startswith(("+", "-")) and not line.startswith(("+++", "---")):
            changed += 1
    return files, changed


def v_apply_patch(a: dict) -> dict:
    diff = a.get("unified_diff")
    if not isinstance(diff, str) or "@@" not in diff:
        raise ValidationError("unified_diff must be a unified diff with @@ hunks")
    if not diff.endswith("\n"):
        diff += "\n"
    files, changed = patch_files_and_size(diff)
    if not files:
        raise ValidationError("patch names no files")
    if changed > MAX_PATCH_LINES:
        raise ValidationError(f"patch changes {changed} lines (max {MAX_PATCH_LINES})")
    for f in files:
        p = PurePosixPath(f)
        if p.is_absolute() or ".." in p.parts:
            raise ValidationError(f"patch path {f!r} is outside shop_repo")
        if p.parts[0] in {"tests", "config"}:
            raise ValidationError(f"patches may not touch {p.parts[0]}/** ({f})")
        if p.parts[0] != "app":
            raise ValidationError(f"patches may only touch app/** ({f})")
    return {"unified_diff": diff}


def v_escalate(a: dict) -> dict:
    reason = str(a.get("reason") or "").strip()
    if not reason:
        raise ValidationError("reason is required")
    return {"reason": reason[:500], "summary": str(a.get("summary") or "")[:3000]}


def v_none(a: dict) -> dict:
    return {}


ACTION_TOOLS = {"restart_service", "revert_config", "rollback_deploy", "apply_patch"}

H = {"type": "object", "properties": {"cause": {"type": "string"}, "confidence": {"type": "number"},
                                      "evidence": {"type": "array", "items": {"type": "string"}}},
     "required": ["cause", "confidence", "evidence"]}

TOOLS: dict[str, ToolSpec] = {t.name: t for t in [
    ToolSpec("get_incident", READ, "Current incident ticket: signal, priority, deploy info, metric snapshot summary, sample error logs, KB matches.",
             _obj({}), v_none),
    ToolSpec("query_metrics", READ, "Time series for one metric from the monitoring database.",
             _obj({"metric": {"type": "string", "enum": sorted(METRICS)},
                   "endpoint": {"type": "string", "enum": sorted(ENDPOINTS)},
                   "window_s": {"type": "integer", "description": "10-3600"}}, ["metric"]), v_query_metrics),
    ToolSpec("read_logs", READ, "Recent shop log records (masked). Each line has an id like log#123.",
             _obj({"since_s": {"type": "integer"}, "level": {"type": "string", "enum": ["INFO", "WARNING", "ERROR"]},
                   "contains": {"type": "string"}, "limit": {"type": "integer", "description": "≤ 200"}}), v_read_logs),
    ToolSpec("list_deploys", READ, "Most recent deploys: tag, SHA, message, time, files changed.",
             _obj({"n": {"type": "integer"}}), v_list_deploys),
    ToolSpec("git_diff", READ, "Unified diff between two git refs (deploy tags or SHAs), size-capped.",
             _obj({"from_ref": {"type": "string"}, "to_ref": {"type": "string"}}, ["from_ref", "to_ref"]), v_git_diff),
    ToolSpec("read_file", READ, "Read lines of a file inside shop_repo (max 200 lines).",
             _obj({"path": {"type": "string"}, "start": {"type": "integer"}, "end": {"type": "integer"}}, ["path"]), v_read_file),
    ToolSpec("search_knowledge_base", READ, "Search runbooks and past postmortems. Returns KB ids to cite.",
             _obj({"query": {"type": "string"}, "k": {"type": "integer", "description": "≤ 5"}}, ["query"]), v_search_kb),
    ToolSpec("run_tests", READ, "Run the shop test suite on a temporary worktree at a git ref (default HEAD).",
             _obj({"ref": {"type": "string"}}), v_run_tests),
    ToolSpec("record_decision", READ,
             "REQUIRED before any action or escalation. Record hypotheses with confidence and evidence ids, the chosen action and why.",
             _obj({"hypotheses": {"type": "array", "items": H},
                   "chosen_action": {"type": "string", "enum": sorted(ACTION_TOOLS | {"escalate", "none"})},
                   "rationale": {"type": "string", "description": "≤ 3 sentences"},
                   "expected_effect": {"type": "string"}, "risk": {"type": "string"}},
                  ["hypotheses", "chosen_action", "rationale", "expected_effect", "risk"]), v_record_decision),
    ToolSpec("restart_service", LOW, "Restart the shop process. Treats resource symptoms only.", _obj({}), v_restart),
    ToolSpec("revert_config", GATED, "Set one config key back to its value from a previous deploy. Needs human approval.",
             _obj({"key": {"type": "string"}, "to_deploy": {"type": "string"}}, ["key", "to_deploy"]), v_revert_config),
    ToolSpec("rollback_deploy", GATED, "Roll production back to a previous deploy tag. Needs human approval.",
             _obj({"to_tag": {"type": "string"}}, ["to_tag"]), v_rollback),
    ToolSpec("apply_patch", GATED,
             "Last resort: apply a small unified diff (≤ 30 changed lines, app/** only). Tests must pass first. Needs human approval.",
             _obj({"unified_diff": {"type": "string"}}, ["unified_diff"]), v_apply_patch),
    ToolSpec("escalate", READ, "Hand the incident to the human on-call with a structured summary. Use when unsure or nothing safe can fix it.",
             _obj({"reason": {"type": "string"}, "summary": {"type": "string"}}, ["reason", "summary"]), v_escalate),
]}


def validate(name: str, args: dict | None) -> dict:
    spec = TOOLS.get(name)
    if spec is None:
        raise ValidationError(f"unknown tool {name!r}; allowed: {sorted(TOOLS)}")
    if args is not None and not isinstance(args, dict):
        raise ValidationError("arguments must be an object")
    return spec.validate(dict(args or {}))
