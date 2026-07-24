import pytest
from pydantic import ValidationError

from app.contracts.roles import ContractRef
from app.contracts.swarm import (
    AgentEndpoint,
    ChiefAuditor,
    RouteMapEntry,
    SwarmContract,
    SwarmScaling,
    SwarmTopology,
    TaskWeightRule,
    WorkerAuditorPair,
)
from app.schemas.enums import RiskPolicy


def _valid_contract() -> SwarmContract:
    return SwarmContract(
        contract_version="1.0",
        topology=SwarmTopology(
            orchestrator_id="orchestrator",
            chief_auditor=ChiefAuditor(agent_id="chief-auditor"),
            min_worker_auditor_pairs=3,
        ),
        worker_auditor_pairs=[
            WorkerAuditorPair(worker_id="worker-1", auditor_id="auditor-1"),
            WorkerAuditorPair(worker_id="worker-2", auditor_id="auditor-2"),
            WorkerAuditorPair(worker_id="worker-3", auditor_id="auditor-3"),
        ],
        swarm_scaling=SwarmScaling(default_pairs=3, min_pairs=3, max_pairs=12),
        route_map=[
            RouteMapEntry(
                source=AgentEndpoint.ORCHESTRATOR,
                target=AgentEndpoint.WORKER,
                reason="assign_step",
                input_contract=ContractRef(name="worker_assignment"),
                output_contract=ContractRef(name="worker_result"),
            ),
            RouteMapEntry(
                source=AgentEndpoint.WORKER,
                target=AgentEndpoint.ASSIGNED_AUDITOR,
                reason="submit_evidence",
                input_contract=ContractRef(name="worker_result"),
                output_contract=ContractRef(name="audit_verdict"),
            ),
            RouteMapEntry(
                source=AgentEndpoint.ASSIGNED_AUDITOR,
                target=AgentEndpoint.CHIEF_AUDITOR,
                reason="escalate_verdict",
                input_contract=ContractRef(name="audit_verdict"),
                output_contract=ContractRef(name="chief_audit_verdict"),
            ),
            RouteMapEntry(
                source=AgentEndpoint.CHIEF_AUDITOR,
                target=AgentEndpoint.ORCHESTRATOR,
                reason="return_final_gate",
                input_contract=ContractRef(name="chief_audit_verdict"),
                output_contract=ContractRef(name="human_review_packet"),
            ),
        ],
        task_weight_rules=[
            TaskWeightRule(
                weight="small",
                max_steps=1,
                risk_policies=[RiskPolicy.READ_ONLY],
                worker_auditor_pairs=3,
            ),
            TaskWeightRule(weight="large", min_steps=6, worker_auditor_pairs=5),
        ],
    )


def test_valid_swarm_contract_has_minimum_three_worker_auditor_pairs():
    contract = _valid_contract()

    assert len(contract.worker_auditor_pairs) == 3
    assert contract.worker_auditor_pairs[0].worker_id == "worker-1"
    assert contract.worker_auditor_pairs[0].auditor_id == "auditor-1"


def test_swarm_contract_rejects_less_than_three_pairs():
    payload = _valid_contract().model_dump(mode="python")
    payload["worker_auditor_pairs"] = [
        {"worker_id": "worker-1", "auditor_id": "auditor-1"},
        {"worker_id": "worker-2", "auditor_id": "auditor-2"},
    ]

    with pytest.raises(ValidationError):
        SwarmContract.model_validate(payload)


def test_swarm_contract_rejects_worker_without_unique_auditor():
    payload = _valid_contract().model_dump(mode="python")
    payload["worker_auditor_pairs"][1]["auditor_id"] = "auditor-1"

    with pytest.raises(ValidationError):
        SwarmContract.model_validate(payload)


def test_swarm_contract_requires_worker_to_assigned_auditor_route():
    payload = _valid_contract().model_dump(mode="python")
    payload["route_map"] = [route for route in payload["route_map"] if route["reason"] != "submit_evidence"]

    with pytest.raises(ValidationError):
        SwarmContract.model_validate(payload)


def test_scaling_rule_is_bounded_by_configured_maximum():
    payload = _valid_contract().model_dump(mode="python")
    payload["task_weight_rules"][1]["worker_auditor_pairs"] = 99

    with pytest.raises(ValidationError):
        SwarmContract.model_validate(payload)
