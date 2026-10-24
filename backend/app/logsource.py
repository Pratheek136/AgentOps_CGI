"""Reads the shop's structured JSON log through the runtime's logs_path."""
from __future__ import annotations

import json
import time
from collections import deque
from datetime import datetime

from .config import paths
from .runtime import get_shop_runtime


def _ts(rec: dict) -> float:
    try:
        return datetime.fromisoformat(rec["ts"]).timestamp()
    except (KeyError, ValueError):
        return 0.0


def read(since_s: int = 300, level: str | None = None, contains: str | None = None,
         limit: int = 50, tail_lines: int = 20000) -> list[dict]:
    """Most recent matching records (oldest first), each with its line number in the file."""
    path = get_shop_runtime().logs_path
    if not path.exists():
        return []
    cutoff = time.time() - since_s
    buf: deque[tuple[int, str]] = deque(maxlen=tail_lines)
    with open(path, encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f, start=1):
            buf.append((i, line))
    out: deque[dict] = deque(maxlen=max(1, min(limit, 200)))
    for line_no, line in buf:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if _ts(rec) < cutoff:
            continue
        if level and rec.get("level", "").upper() != level.upper():
            continue
        if contains and contains.lower() not in line.lower():
            continue
        rec["line"] = line_no
        out.append(rec)
    return list(out)


def format_record(rec: dict, with_traceback: bool = True) -> str:
    parts = [f"log#{rec.get('line')}", rec.get("ts", ""), rec.get("level", ""), rec.get("endpoint", ""),
             str(rec.get("status", "")), f"{rec.get('error_type', '')}: {rec.get('message', '')}".strip(": ")]
    s = " | ".join(p for p in parts if p)
    if with_traceback and rec.get("traceback"):
        tb = rec["traceback"].replace(str(paths.shop_repo) + "/", "").replace(str(paths.shop_repo) + "\\", "")
        tb = tb.strip().splitlines()
        s += "\n    " + "\n    ".join(tb[-6:])
    return s
