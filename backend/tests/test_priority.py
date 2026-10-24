import pytest

from app.priority import Signals, compute, is_higher, matrix


@pytest.mark.parametrize("impact,urgency,expected", [
    ("High", "High", "P1"), ("High", "Medium", "P2"), ("Medium", "High", "P2"),
    ("Medium", "Medium", "P3"), ("Low", "High", "P4"), ("Low", "Medium", "P4"),
])
def test_matrix(impact, urgency, expected):
    assert matrix(impact, urgency) == expected


def test_checkout_outage_is_p1_with_sla():
    r = compute(Signals(revenue_error_rate=1.0, revenue_path_affected=True))
    assert (r.impact, r.urgency, r.priority) == ("High", "High", "P1")
    assert (r.respond_min, r.resolve_min) == (5, 30)


def test_partial_checkout_failure_30pct_is_p1():
    assert compute(Signals(revenue_error_rate=0.30, revenue_path_affected=True)).priority == "P1"


def test_medium_errors_on_revenue_path_is_p2():
    r = compute(Signals(revenue_error_rate=0.10, revenue_path_affected=True))
    assert r.priority == "P2" and r.resolve_min == 120


def test_latency_only_medium_impact():
    r = compute(Signals(revenue_latency_breach=True))
    assert (r.impact, r.priority) == ("Medium", "P3")


def test_memory_only_worsening_is_p4():
    assert compute(Signals(worsening=True)).priority == "P4"


def test_priority_only_increases():
    assert is_higher("P1", "P2") and not is_higher("P3", "P2")
