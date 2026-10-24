"""Shared deploy helpers: commit-and-tag a deploy, chart markers."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from . import db, gitinfo
from .events import bus
from .seed import commit_files

log = logging.getLogger("rootfix.deploys")


def next_tag() -> str:
    tags = gitinfo.deploy_tags()
    return f"deploy-{int(tags[-1].split('-')[1]) + 1 if tags else 1}"


def make_deploy(message: str, files: dict[str, str]) -> str:
    """Commit files on main and tag as the next deploy. Returns the tag."""
    repo = gitinfo.repo()
    if repo.head.is_detached:
        repo.git.checkout("-B", "main")  # main follows what is in production
    sha = commit_files(repo, files, message, datetime.now(timezone.utc))
    tag = next_tag()
    repo.create_tag(tag, message=f"{tag}: {message}")
    log.info("deployed %s (%s): %s", tag, sha[:7], message)
    return tag


def add_marker(kind: str, label: str, incident_id: str | None = None) -> None:
    ts = time.time()
    db.execute("INSERT INTO markers (ts, kind, label, incident_id) VALUES (?,?,?,?)",
               (ts, kind, label, incident_id))
    bus.publish("marker", {"ts": ts, "kind": kind, "label": label})
