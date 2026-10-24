"""Creates shop_repo/ as a real git repo with 5 good deploys (deploy-1..deploy-5).

History is built from the final good code in shop/base/ by removing features that
had not been introduced yet at each deploy.
"""
from __future__ import annotations

import os
import shutil
import stat
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from git import Actor, Repo

from .config import paths

DEV = Actor("Shop Dev Team", "dev@shop.example")
LAST_GOOD_TAG = "deploy-5"

PRICING_V1 = '''"""Cart totals."""
from .catalog import get_product


def lookup_coupon(code):
    return None  # coupons not supported yet


def subtotal(items: list[dict]) -> float:
    total = 0.0
    for it in items:
        product = get_product(it["sku"])
        if product is None:
            raise ValueError(f"unknown sku {it['sku']}")
        total += product["price_inr"] * int(it.get("qty", 1))
    return round(total, 2)


def apply_discount(amount: float, coupon) -> float:
    return amount
'''


def _no_coupon_tests(text: str) -> str:
    return text.split("\n\ndef test_checkout_with_coupon")[0] + "\n"


def _no_cache(text: str) -> str:
    return text.replace("from functools import lru_cache\n\n", "").replace("@lru_cache(maxsize=1)\n", "")


def _no_timeout(text: str) -> str:
    return "".join(l for l in text.splitlines(True) if not l.startswith("PAYMENT_TIMEOUT_MS"))


def _pool5(text: str) -> str:
    return text.replace("DB_POOL_SIZE=10", "DB_POOL_SIZE=5")


# (deploy number the feature arrives in, file, transform that removes it)
FEATURES: list[tuple[int, str, Callable[[str], str]]] = [
    (2, "app/pricing.py", lambda _t: PRICING_V1),
    (2, "tests/test_checkout.py", _no_coupon_tests),
    (3, "app/catalog.py", _no_cache),
    (4, "config/app.env", _no_timeout),
    (5, "config/app.env", _pool5),
]

COMMITS = [
    "v1.0 initial: catalogue, cart, checkout",
    "add coupons (SAVE10, FEST20, NEWUSER15)",
    "perf: cache product list",
    "payments: add 800 ms gateway timeout",
    "config: raise DB_POOL_SIZE to 10",
]


def _rmtree(p: Path) -> None:
    def onerror(func, path, _exc):  # Windows: git objects are read-only
        os.chmod(path, stat.S_IWRITE)
        func(path)
    if p.exists():
        shutil.rmtree(p, onerror=onerror)


def _base_files() -> dict[str, str]:
    base = paths.shop_template / "base"
    out = {}
    for f in base.rglob("*"):
        if f.is_file() and "__pycache__" not in f.parts and ".pytest_cache" not in f.parts:
            out[f.relative_to(base).as_posix()] = f.read_text(encoding="utf-8")
    return out


def _files_for(deploy: int, base: dict[str, str]) -> dict[str, str]:
    files = dict(base)
    for arrives, path, remove in FEATURES:
        if deploy < arrives:
            files[path] = remove(files[path])
    return files


def commit_files(repo: Repo, files: dict[str, str], message: str, when: datetime | None = None) -> str:
    root = Path(repo.working_tree_dir)
    for rel, text in files.items():
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(text, encoding="utf-8")
    repo.index.add(list(files))
    date = (when or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%S%z")
    c = repo.index.commit(message, author=DEV, committer=DEV, author_date=date, commit_date=date)
    return c.hexsha


def seed_repo() -> None:
    t0 = time.time()
    _rmtree(paths.shop_repo)
    paths.shop_repo.mkdir(parents=True)
    repo = Repo.init(paths.shop_repo, initial_branch="main")
    with repo.config_writer() as cw:
        cw.set_value("user", "name", DEV.name)
        cw.set_value("user", "email", DEV.email)
    base = _base_files()
    base[".gitignore"] = "__pycache__/\n.pytest_cache/\n*.pyc\n"
    now = datetime.now(timezone.utc)
    for i, msg in enumerate(COMMITS, start=1):
        when = now - timedelta(days=(len(COMMITS) - i) * 2 + 1, hours=3 * i)
        commit_files(repo, _files_for(i, base), msg, when)
        repo.create_tag(f"deploy-{i}", message=f"deploy-{i}: {msg}")
    print(f"Seeded {paths.shop_repo} with deploy-1..deploy-{len(COMMITS)} in {time.time() - t0:.1f}s")
