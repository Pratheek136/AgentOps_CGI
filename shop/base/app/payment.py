"""Fake payment gateway client. The "real" gateway lives at the internal URL."""
import hashlib
import os
import random
import time
from pathlib import Path

EXPECTED_URL = "http://payments.internal:9000"
# the gateway only accepts the registered live key (stored as a hash); sk_test_ keys run in test mode
REGISTERED_LIVE_KEY_SHA256 = "bf3da1c9dbdfcfe97ad846f8e4456265dfeda42e3bd432d05accdb0986d1465c"


class PaymentError(Exception):
    pass


class PaymentClient:
    def __init__(self, cfg: dict[str, str]) -> None:
        self.url = cfg.get("PAYMENT_API_URL", "")
        self.api_key = cfg.get("PAYMENT_API_KEY", "")
        self.timeout_ms = int(cfg.get("PAYMENT_TIMEOUT_MS", "800"))

    def charge(self, amount_inr: float, order_id: str) -> str:
        outage = os.getenv("PAYMENT_OUTAGE_FLAG")
        if outage and Path(outage).exists():
            time.sleep(self.timeout_ms / 1000)
            raise PaymentError("payment provider returned 503 Service Unavailable (upstream outage)")
        if self.url != EXPECTED_URL:
            time.sleep(0.05)
            host = self.url.split("//")[-1]
            raise ConnectionError(f"Connection refused: could not connect to payment gateway at {host}")
        if not self._key_accepted():
            time.sleep(0.04)
            raise PaymentError("payment gateway rejected the request: 401 Unauthorized (invalid API key)")
        time.sleep(random.uniform(0.03, 0.12))
        return f"txn_{order_id}"

    def _key_accepted(self) -> bool:
        if self.api_key.startswith("sk_test_"):
            return True
        return hashlib.sha256(self.api_key.encode()).hexdigest() == REGISTERED_LIVE_KEY_SHA256
