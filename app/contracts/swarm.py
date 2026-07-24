from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.contracts.roles import ContractRef
from app.schemas.enums import RiskPolicy


AgentId = Annotated[str, Field(min_length=1, max_length=128)]
RouteReason = Annotated[str, Field(min_length=1, max_length=128)]
TaskWeight = Literal["small", "medium", "large", "critical"]


class AgentEndpoint(StrEnum):
    HUMAN = "human"
    ORCHESTRATOR = "orchestrator"
    WORKER = "worker"
    ASSIGNED_AUDITOR = "assigned_auditor"
    CHIEF_AUDITOR = "chief_auditor"


class ChiefAuditor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: AgentId
    strict_mode: bool = False


class WorkerAuditorPair(BaseModel):
    model_config = ConfigDict(extra="forbid")

    worker_id: AgentId
    auditor_id: AgentId
    capabilities: list[str] = Field(default_factory=list)
    max_parallel_steps: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def reject_self_audit(self) -> "WorkerAuditorPair":
        if self.worker_id == self.auditor_id:
            raise ValueError("worker and auditor must be different agents")
        return self


class SwarmTopology(BaseModel):
    model_config = ConfigDict(extra="forbid")

    orchestrator_id: AgentId = "orchestrator"
    chief_auditor: ChiefAuditor = Field(default_factory=lambda: ChiefAuditor(agent_id="chief-auditor"))
    min_worker_auditor_pairs: int = Field(default=3, ge=3)


class SwarmScaling(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_pairs: int = Field(default=3, ge=3)
    min_pairs: int = Field(default=3, ge=3)
    max_pairs: int = Field(default=12, ge=3)
    scale_by: list[str] = Field(
        default_factory=lambda: ["task_weight", "step_count", "risk_policy", "tool_risk"]
    )

    @model_validator(mode="after")
    def validate_bounds(self) -> "SwarmScaling":
        if self.default_pairs < self.min_pairs or self.default_pairs > self.max_pairs:
            raise ValueError("default_pairs must be inside min/max bounds")
        return self


class RouteMapEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: AgentEndpoint
    target: AgentEndpoint
    reason: RouteReason
    input_contract: ContractRef
    output_contract: ContractRef
    required_events: list[str] = Field(default_factory=list)


class TaskWeightRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weight: TaskWeight
    worker_auditor_pairs: int = Field(ge=3)
    min_steps: int | None = Field(default=None, ge=1)
    max_steps: int | None = Field(default=None, ge=1)
    risk_policies: list[RiskPolicy] = Field(default_factory=list)
    requires_chief_auditor_strict_mode: bool = False

    @model_validator(mode="after")
    def validate_step_range(self) -> "TaskWeightRule":
        if self.min_steps is not None and self.max_steps is not None and self.min_steps > self.max_steps:
            raise ValueError("min_steps cannot be greater than max_steps")
        return self


class UpgradePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allow_minor_upgrade: bool = True
    breaking_changes_require: Literal["new_major_version"] = "new_major_version"
    migration_required_for: list[str] = Field(
        default_factory=lambda: [
            "route_removed",
            "required_field_removed",
            "audit_gate_weakened",
            "worker_auditor_pairing_changed",
        ]
    )
    forbidden_without_explicit_approval: list[str] = Field(
        default_factory=lambda: [
            "remove_assigned_auditor",
            "allow_worker_to_human_route",
            "allow_orchestrator_final_without_chief_audit",
        ]
    )


class SwarmContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    contract_version: str
    topology: SwarmTopology
    worker_auditor_pairs: list[WorkerAuditorPair] = Field(min_length=3)
    swarm_scaling: SwarmScaling
    route_map: list[RouteMapEntry] = Field(min_length=1)
    task_weight_rules: list[TaskWeightRule] = Field(default_factory=list)
    upgrade_policy: UpgradePolicy = Field(default_factory=UpgradePolicy)
    human_output_contract: ContractRef = Field(default_factory=lambda: ContractRef(name="human_review_packet"))

    @model_validator(mode="after")
    def validate_swarm(self) -> "SwarmContract":
        if len(self.worker_auditor_pairs) < self.topology.min_worker_auditor_pairs:
            raise ValueError("worker_auditor_pairs must satisfy topology minimum")

        worker_ids = [pair.worker_id for pair in self.worker_auditor_pairs]
        auditor_ids = [pair.auditor_id for pair in self.worker_auditor_pairs]
        if len(set(worker_ids)) != len(worker_ids):
            raise ValueError("worker ids must be unique")
        if len(set(auditor_ids)) != len(auditor_ids):
            raise ValueError("auditor ids must be unique")

        if self.topology.orchestrator_id in worker_ids or self.topology.orchestrator_id in auditor_ids:
            raise ValueError("orchestrator cannot be a worker or assigned auditor")
        chief_auditor_id = self.topology.chief_auditor.agent_id
        if chief_auditor_id in worker_ids or chief_auditor_id in auditor_ids:
            raise ValueError("chief auditor cannot be a worker or assigned auditor")

        required_routes = {
            (AgentEndpoint.ORCHESTRATOR, AgentEndpoint.WORKER, "assign_step"),
            (AgentEndpoint.WORKER, AgentEndpoint.ASSIGNED_AUDITOR, "submit_evidence"),
            (AgentEndpoint.ASSIGNED_AUDITOR, AgentEndpoint.CHIEF_AUDITOR, "escalate_verdict"),
            (AgentEndpoint.CHIEF_AUDITOR, AgentEndpoint.ORCHESTRATOR, "return_final_gate"),
        }
        declared_routes = {(route.source, route.target, route.reason) for route in self.route_map}
        missing_routes = required_routes - declared_routes
        if missing_routes:
            missing = sorted(str(route) for route in missing_routes)
            raise ValueError(f"missing required swarm routes: {missing}")

        for route in self.route_map:
            if route.source == AgentEndpoint.WORKER and route.target == AgentEndpoint.HUMAN:
                raise ValueError("worker cannot route directly to human")

        for rule in self.task_weight_rules:
            if rule.worker_auditor_pairs > self.swarm_scaling.max_pairs:
                raise ValueError("task weight rule exceeds swarm scaling max_pairs")

        return self
