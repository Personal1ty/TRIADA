import pytest

from app.contracts.execution import ExecutionContract, WriteMode
from app.agents.orchestrator import Orchestrator
from app.schemas.enums import RiskPolicy
from app.services.policy_gate import PolicyContractError, PolicyGate


class WritePlanningProvider:
    async def complete_json(self, prompt: str, *, schema_name: str):
        return {
            "answer": {
                "steps": [
                    {
                        "id": "step-1",
                        "title": "Create report",
                        "description": "Write a report",
                        "allowed_tools": ["write_file"],
                        "command": ["write_file", "reports/result.md", "ok"],
                    }
                ]
            }
        }


def test_policy_gate_rejects_write_contract_without_task_write_permission():
    proposal = ExecutionContract(
        allowed_tools=["write_file"],
        write_mode=WriteMode.CREATE_FILE,
        allowed_paths=["reports/result.md"],
    )

    with pytest.raises(PolicyContractError, match="write capability"):
        PolicyGate().enforce(
            proposal,
            task_allowed_tools=["cat"],
            risk_policy=RiskPolicy.READ_ONLY,
        )


def test_policy_gate_clamps_tools_and_requires_approval_for_write():
    proposal = ExecutionContract(
        allowed_tools=["write_file", "cat"],
        write_mode=WriteMode.CREATE_FILE,
        allowed_paths=["reports/result.md"],
    )

    effective = PolicyGate().enforce(
        proposal,
        task_allowed_tools=["write_file", "cat", "rg"],
        risk_policy=RiskPolicy.HIGH_RISK_WRITE,
    )

    assert effective.allowed_tools == ["write_file", "cat"]
    assert effective.allowed_paths == ["reports/result.md"]
    assert effective.approval_required is True


def test_policy_gate_rejects_paths_outside_workspace_contract():
    proposal = ExecutionContract(
        allowed_tools=["write_file"],
        write_mode=WriteMode.CREATE_FILE,
        allowed_paths=["../outside.md"],
    )

    with pytest.raises(PolicyContractError, match="relative workspace paths"):
        PolicyGate().enforce(
            proposal,
            task_allowed_tools=["write_file"],
            risk_policy=RiskPolicy.HIGH_RISK_WRITE,
        )


@pytest.mark.asyncio
async def test_orchestrator_proposes_write_contract_with_path_and_approval():
    plan = await Orchestrator(WritePlanningProvider()).plan_task(
        goal="write a report",
        allowed_tools=["write_file"],
        acceptance_criteria=["report exists"],
    )

    assert plan.execution_contract.write_mode == WriteMode.CREATE_FILE
    assert plan.execution_contract.allowed_paths == ["reports/result.md"]
    assert plan.execution_contract.approval_required is True
