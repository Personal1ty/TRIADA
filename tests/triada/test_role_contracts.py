from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.contracts.roles import (
    ContractRef,
    HandoffContract,
    RoleContract,
    RoleRoute,
    TriadaContract,
    default_triada_contract,
)
from app.schemas.enums import AgentRole, RiskPolicy


def test_default_triada_contract_has_predictable_role_routes():
    contract = default_triada_contract()

    assert [role.role for role in contract.roles] == [
        AgentRole.ORCHESTRATOR,
        AgentRole.WORKER,
        AgentRole.AUDITOR,
    ]
    assert [(route.source, route.target, route.purpose) for route in contract.routes] == [
        (AgentRole.ORCHESTRATOR, AgentRole.WORKER, "assign_step"),
        (AgentRole.WORKER, AgentRole.AUDITOR, "submit_result"),
        (AgentRole.AUDITOR, AgentRole.ORCHESTRATOR, "return_verdict"),
    ]
    assert contract.route_for(AgentRole.ORCHESTRATOR, "assign_step").target == AgentRole.WORKER
    assert contract.route_for(AgentRole.WORKER, "submit_result").target == AgentRole.AUDITOR
    assert contract.route_for(AgentRole.AUDITOR, "return_verdict").target == AgentRole.ORCHESTRATOR


def test_handoff_contract_carries_input_and_output_contract_refs():
    task_id = uuid4()
    trace_id = uuid4()
    handoff = HandoffContract(
        trace_id=trace_id,
        task_id=task_id,
        source=AgentRole.ORCHESTRATOR,
        target=AgentRole.WORKER,
        purpose="assign_step",
        input_contract=ContractRef(name="plan_step", version="1.0"),
        output_contract=ContractRef(name="worker_result", version="1.0"),
        allowed_tools=["git"],
        risk_policy=RiskPolicy.READ_ONLY,
        acceptance_criteria=["git status returned"],
    )

    assert handoff.source == AgentRole.ORCHESTRATOR
    assert handoff.target == AgentRole.WORKER
    assert handoff.input_contract.name == "plan_step"
    assert handoff.output_contract.name == "worker_result"
    assert handoff.allowed_tools == ["git"]


def test_handoff_contract_rejects_same_source_and_target():
    with pytest.raises(ValidationError):
        HandoffContract(
            trace_id=uuid4(),
            task_id=uuid4(),
            source=AgentRole.WORKER,
            target=AgentRole.WORKER,
            purpose="loop",
            input_contract=ContractRef(name="worker_result", version="1.0"),
            output_contract=ContractRef(name="worker_result", version="1.0"),
        )


def test_triada_contract_requires_routes_to_reference_declared_roles():
    with pytest.raises(ValidationError):
        TriadaContract(
            roles=[
                RoleContract(
                    role=AgentRole.ORCHESTRATOR,
                    owns=["planning"],
                    input_contracts=[ContractRef(name="task_request", version="1.0")],
                    output_contracts=[ContractRef(name="task_plan", version="1.0")],
                )
            ],
            routes=[
                RoleRoute(
                    source=AgentRole.ORCHESTRATOR,
                    target=AgentRole.WORKER,
                    purpose="assign_step",
                    input_contract=ContractRef(name="task_plan", version="1.0"),
                    output_contract=ContractRef(name="worker_result", version="1.0"),
                )
            ],
        )


def test_triada_contract_rejects_duplicate_routes():
    role_contracts = [
        RoleContract(
            role=AgentRole.ORCHESTRATOR,
            owns=["planning"],
            input_contracts=[ContractRef(name="task_request", version="1.0")],
            output_contracts=[ContractRef(name="task_plan", version="1.0")],
        ),
        RoleContract(
            role=AgentRole.WORKER,
            owns=["execution"],
            input_contracts=[ContractRef(name="task_plan", version="1.0")],
            output_contracts=[ContractRef(name="worker_result", version="1.0")],
        ),
    ]
    route = RoleRoute(
        source=AgentRole.ORCHESTRATOR,
        target=AgentRole.WORKER,
        purpose="assign_step",
        input_contract=ContractRef(name="task_plan", version="1.0"),
        output_contract=ContractRef(name="worker_result", version="1.0"),
    )

    with pytest.raises(ValidationError):
        TriadaContract(roles=role_contracts, routes=[route, route])
