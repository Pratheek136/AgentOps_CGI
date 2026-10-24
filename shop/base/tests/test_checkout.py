import pytest

from app.main import create_app
from app.payment import EXPECTED_URL

CFG = {"PAYMENT_API_URL": EXPECTED_URL, "PAYMENT_API_KEY": "sk_test_rootfix", "PAYMENT_TIMEOUT_MS": "100"}


@pytest.fixture()
def client():
    return create_app(CFG).test_client()


def test_checkout_without_coupon(client):
    r = client.post("/checkout", json={"items": [{"sku": "TEA-001", "qty": 2}]})
    assert r.status_code == 200
    assert r.get_json()["total_inr"] == 698


def test_checkout_with_coupon(client):
    r = client.post("/checkout", json={"items": [{"sku": "RIC-004", "qty": 1}], "coupon": "SAVE10"})
    assert r.status_code == 200
    assert r.get_json()["total_inr"] == pytest.approx(809.1)


def test_unknown_coupon_is_ignored(client):
    r = client.post("/checkout", json={"items": [{"sku": "DAL-006", "qty": 1}], "coupon": "NOPE"})
    assert r.status_code == 200
    assert r.get_json()["total_inr"] == 189
