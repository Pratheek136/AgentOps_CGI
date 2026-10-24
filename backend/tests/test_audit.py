from app import audit


def test_chain_verifies(temp_db):
    for i in range(5):
        audit.append("agent", "tool.call", incident_id="INC-0001", tool="read_logs", args={"i": i})
    assert audit.verify_chain() == {"ok": True, "count": 5, "broken_at": None, "reason": None}


def test_tampering_one_row_breaks_chain(temp_db):
    for i in range(5):
        audit.append("agent", "tool.call", incident_id="INC-0001", tool="read_logs", args={"i": i})
    temp_db.execute("UPDATE audit SET actor = 'Mallory' WHERE seq = 3")
    res = audit.verify_chain()
    assert res["ok"] is False and res["broken_at"] == 3


def test_deleting_a_row_breaks_chain(temp_db):
    for i in range(4):
        audit.append("system", "status.change", args={"i": i})
    temp_db.execute("DELETE FROM audit WHERE seq = 2")
    res = audit.verify_chain()
    assert res["ok"] is False and res["broken_at"] == 3


def test_args_are_masked(temp_db):
    row = audit.append("agent", "tool.call", args={"line": "PAYMENT_API_KEY=sk_live_abcdef1234567"})
    assert "sk_live_abcdef1234567" not in row["args"]
