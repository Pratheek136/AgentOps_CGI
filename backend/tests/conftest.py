import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db  # noqa: E402
from app.config import paths  # noqa: E402

REAL_DB = paths.db


@pytest.fixture()
def temp_db(tmp_path):
    db.set_db_path(tmp_path / "test.db")
    db.init_db()
    yield db
    db.set_db_path(REAL_DB)


@pytest.fixture()
def temp_repo(tmp_path, monkeypatch):
    """A freshly seeded shop_repo in a temp dir (never touches the running demo)."""
    originals = {k: getattr(paths, k) for k in ("shop_repo", "data", "logs")}
    object.__setattr__(paths, "shop_repo", tmp_path / "shop_repo")
    object.__setattr__(paths, "data", tmp_path / "data")
    object.__setattr__(paths, "logs", tmp_path / "logs")
    from app.seed import seed_repo
    seed_repo()
    yield paths.shop_repo
    for k, v in originals.items():
        object.__setattr__(paths, k, v)


@pytest.fixture()
def p1_incident(temp_db):
    db.execute("INSERT INTO incidents (id, seq, service, status, priority, created_at, first_seen) "
               "VALUES ('INC-0001', 1, 'shop', 'Investigating', 'P1', ?, ?)", (time.time(), time.time()))
    return "INC-0001"
