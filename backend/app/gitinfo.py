"""Read-only git helpers for shop_repo (deploy tags, current version)."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from git import Repo

from .config import paths

DEPLOY_RE = re.compile(r"deploy-(\d+)")


def repo() -> Repo:
    return Repo(paths.shop_repo)


def deploy_tags(r: Repo | None = None) -> list[str]:
    r = r or repo()
    tags = [t.name for t in r.tags if DEPLOY_RE.fullmatch(t.name)]
    return sorted(tags, key=lambda t: int(t.split("-")[1]))


def list_deploys(n: int = 10) -> list[dict]:
    r = repo()
    out = []
    for name in deploy_tags(r)[-n:]:
        c = r.tags[name].commit
        out.append({
            "tag": name,
            "sha": c.hexsha[:7],
            "message": c.message.strip().splitlines()[0],
            "time": datetime.fromtimestamp(c.committed_date, tz=timezone.utc).isoformat(timespec="seconds"),
            "files_changed": list(c.stats.files.keys()),
        })
    return out


def current_deploy() -> dict:
    """Tag + SHA of HEAD, and the previous deploy tag."""
    r = repo()
    head = r.head.commit.hexsha
    tags = deploy_tags(r)
    current = next((t for t in reversed(tags) if r.tags[t].commit.hexsha == head), None)
    prev = None
    if current:
        idx = tags.index(current)
        prev = tags[idx - 1] if idx > 0 else None
    return {"tag": current, "sha": head[:7], "prev_tag": prev, "detached": r.head.is_detached}
