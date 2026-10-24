"""SQLite schema and small helpers. WAL mode: traffic writes orders concurrently."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable

from .config import paths

SCHEMA = """
CREATE TABLE IF NOT EXISTS metrics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  endpoint TEXT NOT NULL,
  requests INTEGER, errors INTEGER, error_rate REAL,
  p50_ms REAL, p95_ms REAL, memory_mb REAL, healthy INTEGER, version TEXT
);
CREATE INDEX IF NOT EXISTS ix_metrics_ts ON metrics(ts);
CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL, order_id TEXT, status_code INTEGER, ok INTEGER,
  value_inr REAL, coupon TEXT, error TEXT, latency_ms REAL
);
CREATE INDEX IF NOT EXISTS ix_orders_ts ON orders(ts);
CREATE TABLE IF NOT EXISTS incidents (
  id TEXT PRIMARY KEY, seq INTEGER, service TEXT, endpoints TEXT, alert_rule TEXT,
  signal TEXT, first_seen REAL, created_at REAL, status TEXT, priority TEXT,
  impact TEXT, urgency TEXT, priority_reason TEXT, snapshot TEXT, sample_logs TEXT,
  deploy_tag TEXT, deploy_sha TEXT, prev_tag TEXT, kb_matches TEXT,
  responded_at REAL, resolved_at REAL, closed_at REAL, escalated_at REAL,
  scenario TEXT, verification TEXT, impact_json TEXT, report_md TEXT, escalation TEXT
);
CREATE TABLE IF NOT EXISTS status_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id TEXT, ts REAL,
  from_status TEXT, to_status TEXT, actor TEXT, reason TEXT
);
CREATE TABLE IF NOT EXISTS priority_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id TEXT, ts REAL,
  from_priority TEXT, to_priority TEXT, actor TEXT, reason TEXT
);
CREATE TABLE IF NOT EXISTS audit (
  seq INTEGER PRIMARY KEY, ts REAL, incident_id TEXT, actor TEXT, action TEXT,
  tool TEXT, args TEXT, result TEXT, evidence TEXT, approval_id TEXT,
  prev_hash TEXT, hash TEXT
);
CREATE TABLE IF NOT EXISTS approvals (
  id TEXT PRIMARY KEY, incident_id TEXT, created_at REAL, status TEXT, tool TEXT,
  args TEXT, diff_preview TEXT, risk TEXT, evidence TEXT, hypothesis TEXT,
  confidence REAL, expected_effect TEXT, rollback_plan TEXT, summary TEXT,
  approver TEXT, reason TEXT, decided_at REAL, executed_at REAL, consumed INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS trace (
  id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id TEXT, ts REAL, kind TEXT,
  summary TEXT, data TEXT
);
CREATE TABLE IF NOT EXISTS tool_results (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT, incident_id TEXT, ts REAL, tool TEXT, args TEXT,
  output TEXT, flagged INTEGER DEFAULT 0, UNIQUE (incident_id, id)
);
CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id TEXT, ts REAL, stage TEXT, message TEXT
);
CREATE TABLE IF NOT EXISTS markers (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, label TEXT, incident_id TEXT
);
"""

RESET_TABLES = [
    "metrics", "orders", "incidents", "status_history", "priority_history", "audit",
    "approvals", "trace", "tool_results", "notifications", "markers",
]

_local = threading.local()
_db_path: Path = paths.db


def set_db_path(p: Path) -> None:
    """Used by tests to point at a temporary database."""
    global _db_path
    _db_path = p
    _local.__dict__.clear()


def conn() -> sqlite3.Connection:
    c: sqlite3.Connection | None = getattr(_local, "conn", None)
    if c is None or getattr(_local, "path", None) != _db_path:
        _db_path.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(_db_path, timeout=10, isolation_level=None, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=5000")
        _local.conn = c
        _local.path = _db_path
    return c


def init_db() -> None:
    c = conn()
    cols = [r[1] for r in c.execute("PRAGMA table_info(tool_results)").fetchall()]
    if cols and "seq" not in cols:  # pre-M7 schema: tool result ids were global
        c.execute("DROP TABLE tool_results")
    c.executescript(SCHEMA)


def execute(sql: str, params: Iterable[Any] = ()) -> int:
    cur = conn().execute(sql, tuple(params))
    return cur.lastrowid or 0


def query(sql: str, params: Iterable[Any] = ()) -> list[dict]:
    return [dict(r) for r in conn().execute(sql, tuple(params)).fetchall()]


def one(sql: str, params: Iterable[Any] = ()) -> dict | None:
    r = conn().execute(sql, tuple(params)).fetchone()
    return dict(r) if r else None


def dumps(v: Any) -> str:
    return json.dumps(v, default=str, ensure_ascii=False)


def loads(s: str | None, default: Any = None) -> Any:
    if not s:
        return default
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return default


def reset_runtime_data() -> None:
    """Clear incidents/metrics/orders etc. Keeps KB and replay fixtures (on disk)."""
    c = conn()
    for t in RESET_TABLES:
        c.execute(f"DELETE FROM {t}")
