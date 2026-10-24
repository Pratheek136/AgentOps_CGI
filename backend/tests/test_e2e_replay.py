"""Scenario 1 end to end with the replay provider, against the running stack.

Needs `python scripts/demo.py up` (skips otherwise). Uses recorded fixtures only: no LLM quota.
Note: this resets the demo.
"""
import time

import httpx
import pytest

B = "http://127.0.0.1:8000"


def _up() -> bool:
    try:
        return httpx.get(f"{B}/api/health", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(not _up(), reason="stack not running (python scripts/demo.py up)")


def _wait(pred, timeout: float, step: float = 2.0):
    end = time.time() + timeout
    while time.time() < end:
        v = pred()
        if v:
            return v
        time.sleep(step)
    raise AssertionError("timed out")


def test_scenario1_replay_end_to_end():
    c = httpx.Client(base_url=B, timeout=60)
    assert c.post("/api/demo/reset").json()["seconds"] < 20
    time.sleep(5)
    c.post("/api/demo/fault/1", params={"provider": "replay"}).raise_for_status()

    inc = _wait(lambda: c.get("/api/incidents/active").json(), 60)
    assert inc["priority"] == "P1" and inc["kb_matches"][0]["id"] in {"RB-01", "PM-01"}

    apr = _wait(lambda: (c.get("/api/approvals", params={"status": "pending"}).json() or [None])[0], 120)
    assert apr["tool"] == "revert_config" and apr["args"] == {"key": "PAYMENT_API_URL", "to_deploy": "deploy-5"}
    assert apr["rollback_plan"] and apr["evidence"] and "***MASKED***" in apr["diff_preview"]

    # the gate refuses execution before approval
    r = c.post("/api/tools/revert_config", json={"incident_id": inc["id"], "args": apr["args"]})
    assert r.status_code == 403

    c.post(f"/api/approvals/{apr['id']}/decide",
           json={"approver": "Pratheek Shenoy", "decision": "approve", "reason": "e2e test"}).raise_for_status()
    done = _wait(lambda: (lambda i: i if i["status"] in ("Resolved", "Escalated") else None)(
        c.get(f"/api/incidents/{inc['id']}").json()), 150)
    assert done["status"] == "Resolved"

    imp = c.get(f"/api/incidents/{inc['id']}/impact").json()
    assert imp["failed_checkouts"] > 0 and imp["rupees_at_risk"] > 0 and imp["sla_resolve_met"] is True
    report = _wait(lambda: c.get(f"/api/incidents/{inc['id']}/report").json()["markdown"], 30)
    assert "Business impact summary" in report and "sk_live" not in report
    stages = [n["stage"] for n in c.get("/api/notifications").json() if n["incident_id"] == inc["id"]]
    assert {"Triaged", "Awaiting approval", "Resolved"} <= set(stages)
    assert c.get("/api/audit/verify").json()["ok"] is True
