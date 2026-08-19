from app.contracts.capabilities import capability_matrix, capability_registry, check_capability
from app.agents.worker import Worker


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


async def test_worker_role_cannot_execute_when_scoped_as_auditor(tmp_path):
    result = await Worker(worker_id="auditor-1", workspace=tmp_path, role="auditor").run_step(
        task_id="task-1", step_id="step-1", title="Inspect", allowed_tools=["echo"], command=["echo", "hello"]
    )

    assert result.status == "blocked"
    assert "execute_tools" in result.errors[0]


def test_capability_registry_declares_owner_policy_approval_and_audit_event():
    registry = capability_registry()

    assert registry["execute_tools"]["owner"] == "worker"
    assert registry["write_artifacts"]["approval_required"] is True
    assert registry["issue_verdict"]["audit_event"] == "audit_verdict"
