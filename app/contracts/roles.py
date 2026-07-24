from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.enums import AgentRole, RiskPolicy


ContractName = Annotated[str, Field(min_length=1, max_length=128)]
ContractVersion = Annotated[str, Field(pattern=r"^\d+\.\d+$")]
RoutePurpose = Annotated[str, Field(min_length=1, max_length=128)]
Capability = Annotated[str, Field(min_length=1, max_length=128)]
Ref = Annotated[str, Field(min_length=1, max_length=300)]


class ContractRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: ContractName
    version: ContractVersion = "1.0"

    @property
    def ref(self) -> str:
        return f"{self.name}@{self.version}"


class RoleContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: AgentRole
    owns: list[Capability] = Field(min_length=1)
    input_contracts: list[ContractRef] = Field(default_factory=list)
    output_contracts: list[ContractRef] = Field(default_factory=list)
    required_events: list[ContractName] = Field(default_factory=list)
    required_artifacts: list[ContractName] = Field(default_factory=list)
    scalable_by: Literal["role", "task", "step", "trace"] = "role"
    max_parallelism: int | None = Field(default=None, ge=1)


class RoleRoute(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: AgentRole
    target: AgentRole
    purpose: RoutePurpose
    input_contract: ContractRef
    output_contract: ContractRef
    required_events: list[ContractName] = Field(default_factory=list)

    @model_validator(mode="after")
    def reject_self_route(self) -> "RoleRoute":
        if self.source == self.target:
            raise ValueError("role route source and target must differ")
        return self

    @property
    def route_key(self) -> tuple[AgentRole, str]:
        return self.source, self.purpose


class HandoffContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    trace_id: UUID
    task_id: UUID
    source: AgentRole
    target: AgentRole
    purpose: RoutePurpose
    input_contract: ContractRef
    output_contract: ContractRef
    input_refs: list[Ref] = Field(default_factory=list)
    output_refs: list[Ref] = Field(default_factory=list)
    allowed_tools: list[ContractName] = Field(default_factory=list)
    risk_policy: RiskPolicy = RiskPolicy.READ_ONLY
    acceptance_criteria: list[Ref] = Field(default_factory=list)
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)

    @model_validator(mode="after")
    def reject_self_handoff(self) -> "HandoffContract":
        if self.source == self.target:
            raise ValueError("handoff source and target must differ")
        return self


class TriadaContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    roles: list[RoleContract] = Field(min_length=1)
    routes: list[RoleRoute] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_graph(self) -> "TriadaContract":
        declared_roles = {role.role for role in self.roles}
        if len(declared_roles) != len(self.roles):
            raise ValueError("duplicate role contracts are not allowed")

        route_keys: set[tuple[AgentRole, str]] = set()
        for route in self.routes:
            if route.source not in declared_roles:
                raise ValueError(f"route source is not declared: {route.source}")
            if route.target not in declared_roles:
                raise ValueError(f"route target is not declared: {route.target}")
            if route.route_key in route_keys:
                raise ValueError(f"duplicate route for source/purpose: {route.source}/{route.purpose}")
            route_keys.add(route.route_key)
        return self

    def role_contract(self, role: AgentRole) -> RoleContract:
        for contract in self.roles:
            if contract.role == role:
                return contract
        raise KeyError(f"role contract not found: {role}")

    def route_for(self, source: AgentRole, purpose: str) -> RoleRoute:
        for route in self.routes:
            if route.source == source and route.purpose == purpose:
                return route
        raise KeyError(f"route not found: {source}/{purpose}")


def default_triada_contract() -> TriadaContract:
    task_request = ContractRef(name="task_request", version="1.0")
    task_plan = ContractRef(name="task_plan", version="1.0")
    plan_step = ContractRef(name="plan_step", version="1.0")
    worker_result = ContractRef(name="worker_result", version="1.0")
    audit_verdict = ContractRef(name="audit_verdict", version="1.0")
    thinking_delta = ContractRef(name="thinking_summary_delta", version="1.0")
    model_reasoning = ContractRef(name="model_reasoning_content_captured", version="1.0")

    return TriadaContract(
        roles=[
            RoleContract(
                role=AgentRole.ORCHESTRATOR,
                owns=["planning", "routing", "risk_classification"],
                input_contracts=[task_request, audit_verdict],
                output_contracts=[task_plan, plan_step, thinking_delta, model_reasoning],
                required_events=["planning_started", "planning_completed", "thinking_summary_delta"],
                scalable_by="task",
            ),
            RoleContract(
                role=AgentRole.WORKER,
                owns=["execution", "tool_use", "evidence_collection"],
                input_contracts=[plan_step],
                output_contracts=[worker_result, thinking_delta, model_reasoning],
                required_events=["worker_step_started", "worker_step_completed", "tool_execution_completed"],
                scalable_by="step",
                max_parallelism=32,
            ),
            RoleContract(
                role=AgentRole.AUDITOR,
                owns=["verification", "quality_gate", "correction_routing"],
                input_contracts=[worker_result, thinking_delta],
                output_contracts=[audit_verdict, thinking_delta, model_reasoning],
                required_events=["audit_verdict"],
                scalable_by="trace",
            ),
        ],
        routes=[
            RoleRoute(
                source=AgentRole.ORCHESTRATOR,
                target=AgentRole.WORKER,
                purpose="assign_step",
                input_contract=plan_step,
                output_contract=worker_result,
                required_events=["worker_step_started"],
            ),
            RoleRoute(
                source=AgentRole.WORKER,
                target=AgentRole.AUDITOR,
                purpose="submit_result",
                input_contract=worker_result,
                output_contract=audit_verdict,
                required_events=["worker_step_completed", "tool_execution_completed"],
            ),
            RoleRoute(
                source=AgentRole.AUDITOR,
                target=AgentRole.ORCHESTRATOR,
                purpose="return_verdict",
                input_contract=audit_verdict,
                output_contract=task_plan,
                required_events=["audit_verdict"],
            ),
        ],
    )
