"""Cart totals and coupon handling."""
from dataclasses import dataclass

from .catalog import get_product


@dataclass(frozen=True)
class Coupon:
    code: str
    percent: int


COUPONS = {
    "SAVE10": Coupon("SAVE10", 10),
    "FEST20": Coupon("FEST20", 20),
    "NEWUSER15": Coupon("NEWUSER15", 15),
}


def lookup_coupon(code: str | None) -> Coupon | None:
    if not code:
        return None
    return COUPONS.get(code.upper())


def subtotal(items: list[dict]) -> float:
    total = 0.0
    for it in items:
        product = get_product(it["sku"])
        if product is None:
            raise ValueError(f"unknown sku {it['sku']}")
        total += product["price_inr"] * int(it.get("qty", 1))
    return round(total, 2)


def apply_discount(amount: float, coupon: Coupon | None) -> float:
    if coupon is None:
        return amount
    return round(amount * (100 - coupon.percent) / 100, 2)
