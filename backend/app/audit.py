"""Append-only, SHA-256 hash-chained audit log."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any

from . import db
from .events import bus
from .security import mask_obj

GENESIS = "0" * 64
_lock = threading.Lock()

FIELDS = ["seq", "ts", "incident_id", "actor", "action", "tool", "args", "result",
          "evidence", "approval_id", "prev_hash"]


def _canonical(row: dict) -> str:
    return json.dumps({k: row.get(k) for k in FIELDS}, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=str)


def compute_hash(row: dict) -> str:
    return hashlib.sha256((row["prev_hash"] + _canonical(row)).encode("utf-8")).hexdigest()


def append(actor: str, action: str, *, incident_id: str | None = None, tool: str | None = None,
           args: Any = None, result: Any = None, evidence: list[str] | None = None,
           approval_id: str | None = None) -> dict:
    with _lock:
        last = db.one("SELECT seq, hash FROM audit ORDER BY seq DESC LIMIT 1")
        row = {
            "seq": (last["seq"] + 1) if last else 1,
            "ts": round(time.time(), 6),
            "incident_id": incident_id,
            "actor": actor,
            "action": action,
            "tool": tool,
            "args": db.dumps(mask_obj(args)) if args is not None else None,
            "result": db.dumps(mask_obj(result)) if result is not None else None,
            "evidence": db.dumps(evidence) if evidence else None,
            "approval_id": approval_id,
            "prev_hash": last["hash"] if last else GENESIS,
        }
        row["hash"] = compute_hash(row)
        db.execute(
            "INSERT INTO audit (seq, ts, incident_id, actor, action, tool, args, result, evidence, "
            "approval_id, prev_hash, hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [row[k] for k in FIELDS] + [row["hash"]],
        )
    bus.publish("audit", row)
    return row


def verify_chain() -> dict:
    rows = db.query("SELECT * FROM audit ORDER BY seq")
    prev = GENESIS
    for r in rows:
        if r["prev_hash"] != prev:
            return {"ok": False, "count": len(rows), "broken_at": r["seq"], "reason": "prev_hash mismatch"}
        if compute_hash(r) != r["hash"]:
            return {"ok": False, "count": len(rows), "broken_at": r["seq"], "reason": "row content altered"}
        prev = r["hash"]
    return {"ok": True, "count": len(rows), "broken_at": None, "reason": None}


def entries(incident_id: str | None = None, limit: int = 500) -> list[dict]:
    if incident_id:
        rows = db.query("SELECT * FROM audit WHERE incident_id = ? ORDER BY seq DESC LIMIT ?", (incident_id, limit))
    else:
        rows = db.query("SELECT * FROM audit ORDER BY seq DESC LIMIT ?", (limit,))
    for r in rows:
        for k in ("args", "result", "evidence"):
            r[k] = db.loads(r[k], r[k])
    return rows
