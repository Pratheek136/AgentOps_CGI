"""Product catalogue (synthetic)."""
from functools import lru_cache

PRODUCTS = [
    {"sku": "TEA-001", "name": "Assam Tea 500g", "price_inr": 349},
    {"sku": "COF-002", "name": "Coorg Coffee 250g", "price_inr": 499},
    {"sku": "SPC-003", "name": "Garam Masala 100g", "price_inr": 129},
    {"sku": "RIC-004", "name": "Basmati Rice 5kg", "price_inr": 899},
    {"sku": "OIL-005", "name": "Cold-pressed Groundnut Oil 1L", "price_inr": 329},
    {"sku": "DAL-006", "name": "Toor Dal 1kg", "price_inr": 189},
    {"sku": "GHE-007", "name": "Desi Ghee 1L", "price_inr": 749},
    {"sku": "HNY-008", "name": "Forest Honey 500g", "price_inr": 399},
]
_BY_SKU = {p["sku"]: p for p in PRODUCTS}


@lru_cache(maxsize=1)
def list_products() -> tuple[dict, ...]:
    return tuple(PRODUCTS)


def get_product(sku: str) -> dict | None:
    return _BY_SKU.get(sku)
