"""Steady synthetic traffic against the demo shop.

Every checkout attempt + outcome (with the client-side cart value) is written to the
`orders` table, so business impact is computed from ground truth. All data is synthetic.
"""
from __future__ import annotations

import os
import random
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import requests

SHOP = os.getenv("SHOP_URL", "http://127.0.0.1:5000")
RPS = float(os.getenv("TRAFFIC_RPS", "3"))
DB = os.getenv("ROOTFIX_DB", "data/rootfix.db")
NO_COUPON_SHARE = 0.30

PRICES = {"TEA-001": 349, "COF-002": 499, "SPC-003": 129, "RIC-004": 899, "OIL-005": 329,
          "DAL-006": 189, "GHE-007": 749, "HNY-008": 399}
COUPONS = {"SAVE10": 10, "FEST20": 20, "NEWUSER15": 15}

_local = threading.local()


def _db() -> sqlite3.Connection:
    c = getattr(_local, "c", None)
    if c is None:
        c = sqlite3.connect(DB, timeout=10, isolation_level=None)
        c.execute("PRAGMA busy_timeout=5000")
        _local.c = c
    return c


def random_cart() -> tuple[list[dict], float]:
    """Random cart with a value between ₹300 and ₹4,000."""
    while True:
        items = [{"sku": s, "qty": random.randint(1, 3)} for s in random.sample(list(PRICES), random.randint(1, 4))]
        value = sum(PRICES[i["sku"]] * i["qty"] for i in items)
        if 300 <= value <= 4000:
            return items, value


def checkout() -> None:
    items, value = random_cart()
    coupon = None if random.random() < NO_COUPON_SHARE else random.choice(list(COUPONS))
    expected = round(value * (100 - COUPONS[coupon]) / 100, 2) if coupon else value
    order_id = f"ord_{uuid.uuid4().hex[:10]}"
    t0 = time.perf_counter()
    status, error = 0, None
    try:
        r = requests.post(f"{SHOP}/checkout", timeout=5,
                          json={"items": items, "coupon": coupon, "order_id": order_id,
                                "expected_value_inr": expected})
        status = r.status_code
        if status >= 400:
            error = (r.json() or {}).get("error", f"HTTP {status}") if r.headers.get("content-type", "").startswith("application/json") else f"HTTP {status}"
    except requests.RequestException as exc:
        error = type(exc).__name__
    latency = (time.perf_counter() - t0) * 1000
    try:
        _db().execute(
            "INSERT INTO orders (ts, order_id, status_code, ok, value_inr, coupon, error, latency_ms) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (time.time(), order_id, status, int(200 <= status < 300), expected, coupon, error, round(latency, 1)),
        )
    except sqlite3.Error as exc:
        print(f"db write failed: {exc}", flush=True)


def browse() -> None:
    try:
        requests.get(f"{SHOP}/products", timeout=5)
        if random.random() < 0.5:
            items, _ = random_cart()
            requests.post(f"{SHOP}/cart", json={"items": items}, timeout=5)
    except requests.RequestException:
        pass


def main() -> None:
    print(f"traffic: {RPS} checkouts/s against {SHOP}, db={DB}", flush=True)
    pool = ThreadPoolExecutor(max_workers=16)
    interval = 1.0 / max(RPS, 0.1)
    next_t = time.perf_counter()
    while True:
        pool.submit(checkout)
        if random.random() < 0.7:
            pool.submit(browse)
        next_t += interval * random.uniform(0.6, 1.4)
        time.sleep(max(0.0, next_t - time.perf_counter()))


if __name__ == "__main__":
    main()
