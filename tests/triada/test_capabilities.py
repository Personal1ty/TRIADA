from app.contracts.capabilities import capability_matrix, check_capability


def test_capability_matrix_keeps_orchestrator_worker_auditor_boundaries_explicit():
    matrix = capability_matrix()

    assert "execute_tools" not in matrix["orchestrator"]["allowed"]
    assert "execute_tools" in matrix["worker"]["allowed"]
    assert "issue_verdict" in matrix["auditor"]["allowed"]
    assert "approve_task" not in matrix["worker"]["allowed"]


def test_capability_check_returns_reason_for_denied_action():
    decision = check_capability("auditor", "execute_tools")

    assert decision == {
        "role": "auditor",
        "capability": "execute_tools",
        "allowed": False,
        "reason": "auditor is not allowed to execute_tools",
    }
