import time

import pytest

from app import db, impact


@pytest.fixture()
def fixture_incident(temp_db):
    t0 = 1_800_000_000.0
    db.execute("INSERT INTO incidents (id, seq, service, alert_rule, status, priority, first_seen, created_at, "
               "responded_at, resolved_at) VALUES ('INC-0001', 1, 'shop', 'checkout_error_rate', 'Resolved', 'P1', "
               "?, ?, ?, ?)", (t0, t0 + 10, t0 + 11, t0 + 250))
    orders = [
        (t0 - 30, 0, 999.0),    # before the window: ignored
        (t0 + 5, 0, 1200.0),
        (t0 + 20, 0, 845.5),
        (t0 + 40, 1, 700.0),    # succeeded: not at risk
        (t0 + 100, 0, 3999.0),
        (t0 + 260, 0, 500.0),   # after recovery: ignored
    ]
    for ts, ok, v in orders:
        db.execute("INSERT INTO orders (ts, ok, value_inr) VALUES (?,?,?)", (ts, ok, v))
    db.execute("INSERT INTO metrics (ts, endpoint, error_rate) VALUES (?, '/checkout', 0.97)", (t0 + 30,))
    return "INC-0001"


def test_rupees_and_counts_from_failed_orders_in_window(fixture_incident):
    imp = impact.compute(fixture_incident)
    assert imp["failed_checkouts"] == 3
    assert imp["checkout_attempts"] == 4
    assert imp["rupees_at_risk"] == pytest.approx(1200.0 + 845.5 + 3999.0)
    assert imp["peak_error_rate"] == pytest.approx(0.97)


def test_downtime_and_sla(fixture_incident):
    imp = impact.compute(fixture_incident)
    assert imp["disruption_minutes"] == pytest.approx(250 / 60, abs=0.05)
    assert imp["time_to_resolve_s"] == pytest.approx(240.0)
    assert imp["sla_resolve_met"] is True and imp["sla_respond_met"] is True
    assert imp["label"] == "synthetic demo data"


def test_sla_missed_when_over_target(temp_db):
    db.execute("INSERT INTO incidents (id, seq, status, priority, first_seen, created_at, responded_at, resolved_at) "
               "VALUES ('INC-0002', 2, 'Resolved', 'P1', 0, 0, 400, 1900)")
    imp = impact.compute("INC-0002")
    assert imp["sla_respond_met"] is False and imp["sla_resolve_met"] is False


def test_inr_formatting():
    assert impact.inr(1234567.4) == "₹12,34,567"
    assert impact.inr(18400) == "₹18,400"
    assert impact.inr(999) == "₹999"
