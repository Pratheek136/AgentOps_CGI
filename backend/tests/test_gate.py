import pytest
from fastapi.testclient import TestClient

from app import approvals, audit, db
from app.main import app
from app.tools.registry import ValidationError, validate

client = TestClient(app)  # no lifespan: nothing is started


def _rejections():
    return [r for r in audit.entries() if r["action"] == "tool.rejected"]


@pytest.mark.parametrize("tool,args", [
    ("rollback_deploy", {"to_tag": "deploy-4"}),
    ("revert_config", {"key": "DB_POOL_SIZE", "to_deploy": "deploy-4"}),
    ("restart_service", {}),  # low tier, but P1 needs approval
])
def test_gated_tool_without_approval_is_403_and_audited(temp_repo, p1_incident, tool, args):
    r = client.post(f"/api/tools/{tool}", json={"incident_id": p1_incident, "args": args})
    assert r.status_code == 403
    rej = _rejections()
    assert rej and rej[0]["tool"] == tool and rej[0]["result"]["status"] == 403
    assert audit.verify_chain()["ok"]


def _approval(incident_id, tool, args):
    return approvals.create(incident_id, tool, args, diff_preview="", risk="medium", evidence=["tr-1"],
                            hypothesis="h", confidence=0.9, expected_effect="e", rollback_plan="r", summary="s")


def test_pending_or_rejected_approval_is_403(temp_repo, p1_incident):
    apr = _approval(p1_incident, "rollback_deploy", {"to_tag": "deploy-4"})
    r = client.post("/api/tools/rollback_deploy",
                    json={"incident_id": p1_incident, "args": {"to_tag": "deploy-4"}, "approval_id": apr["id"]})
    assert r.status_code == 403 and "pending" in r.json()["detail"]
    approvals.decide(apr["id"], "Pratheek Shenoy", False, "prefer config revert")
    r = client.post("/api/tools/rollback_deploy",
                    json={"incident_id": p1_incident, "args": {"to_tag": "deploy-4"}, "approval_id": apr["id"]})
    assert r.status_code == 403 and "rejected" in r.json()["detail"]


def test_approval_for_different_args_is_403(temp_repo, p1_incident):
    apr = _approval(p1_incident, "rollback_deploy", {"to_tag": "deploy-4"})
    approvals.decide(apr["id"], "Samarth Veeraraje Urs", True, "looks right")
    r = client.post("/api/tools/rollback_deploy",
                    json={"incident_id": p1_incident, "args": {"to_tag": "deploy-1"}, "approval_id": apr["id"]})
    assert r.status_code == 403 and "differ" in r.json()["detail"]


def test_viewer_cannot_approve(temp_repo, p1_incident):
    apr = _approval(p1_incident, "rollback_deploy", {"to_tag": "deploy-4"})
    r = client.post(f"/api/approvals/{apr['id']}/decide",
                    json={"approver": "Viewer", "decision": "approve", "reason": "ok"})
    assert r.status_code == 403
    assert approvals.get(apr["id"])["status"] == "pending"


def test_reason_required(temp_repo, p1_incident):
    apr = _approval(p1_incident, "rollback_deploy", {"to_tag": "deploy-4"})
    r = client.post(f"/api/approvals/{apr['id']}/decide",
                    json={"approver": "Pratheek Shenoy", "decision": "approve", "reason": "  "})
    assert r.status_code == 422


def test_read_tool_allowed(temp_repo, p1_incident):
    r = client.post("/api/tools/list_deploys", json={"incident_id": p1_incident, "args": {"n": 3}})
    assert r.status_code == 200 and "deploy-5" in r.json()["text"]


# ---------------------------------------------------------------- validators
@pytest.mark.parametrize("tag", ["deploy-99", "main", "deploy-5", "../deploy-1", 5])
def test_rollback_rejects_bad_tag(temp_repo, tag):
    with pytest.raises(ValidationError):
        validate("rollback_deploy", {"to_tag": tag})


def test_rollback_accepts_ancestor(temp_repo):
    assert validate("rollback_deploy", {"to_tag": "deploy-4"}) == {"to_tag": "deploy-4"}


@pytest.mark.parametrize("path", ["../backend/app/config.py", "/etc/passwd", ".git/config", "app/../../x.py",
                                  "..\\..\\secrets.txt"])
def test_read_file_rejects_paths_outside_repo(temp_repo, path):
    with pytest.raises(ValidationError):
        validate("read_file", {"path": path})


def test_read_file_max_200_lines(temp_repo):
    with pytest.raises(ValidationError):
        validate("read_file", {"path": "app/main.py", "start": 1, "end": 500})


def _patch(path: str, n_lines: int) -> str:
    body = "".join(f"+x{i} = {i}\n" for i in range(n_lines))
    return f"--- a/{path}\n+++ b/{path}\n@@ -1,0 +1,{n_lines} @@\n{body}"


def test_patch_rejects_oversized(temp_repo):
    with pytest.raises(ValidationError, match="max 30"):
        validate("apply_patch", {"unified_diff": _patch("app/pricing.py", 31)})


@pytest.mark.parametrize("path", ["tests/test_checkout.py", "config/app.env", "serve.py", "../evil.py"])
def test_patch_rejects_paths(temp_repo, path):
    with pytest.raises(ValidationError):
        validate("apply_patch", {"unified_diff": _patch(path, 2)})


def test_patch_accepts_small_app_change(temp_repo):
    validate("apply_patch", {"unified_diff": _patch("app/pricing.py", 3)})


def test_revert_config_validation(temp_repo):
    with pytest.raises(ValidationError):
        validate("revert_config", {"key": "NOT_A_KEY", "to_deploy": "deploy-4"})
    with pytest.raises(ValidationError):  # already equal
        validate("revert_config", {"key": "PAYMENT_API_URL", "to_deploy": "deploy-4"})
    assert validate("revert_config", {"key": "DB_POOL_SIZE", "to_deploy": "deploy-4"})["to_deploy"] == "deploy-4"


def test_unknown_tool_rejected():
    with pytest.raises(ValidationError):
        validate("exec", {"cmd": "rm -rf /"})


def test_decision_requires_evidence(temp_db):
    with pytest.raises(ValidationError, match="evidence"):
        validate("record_decision", {"hypotheses": [{"cause": "x", "confidence": 0.9, "evidence": []}],
                                     "chosen_action": "rollback_deploy", "rationale": "r",
                                     "expected_effect": "e", "risk": "low"})
