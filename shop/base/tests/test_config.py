from app.payment import EXPECTED_URL
from app.settings import load_config


def test_config_has_required_keys():
    cfg = load_config()
    for key in ("PAYMENT_API_URL", "PAYMENT_API_KEY", "DB_POOL_SIZE"):
        assert key in cfg


def test_payment_url_points_at_internal_gateway():
    assert load_config()["PAYMENT_API_URL"] == EXPECTED_URL


def test_pool_size_in_range():
    assert 1 <= int(load_config()["DB_POOL_SIZE"]) <= 50
