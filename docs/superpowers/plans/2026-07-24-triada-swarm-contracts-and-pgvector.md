# TRIADA Swarm Contracts And Pgvector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the contract-first TRIADA swarm layer and enable local PostgreSQL as a vector-ready database through pgvector.

**Architecture:** Add pgvector as an infrastructure capability first, then implement machine-checkable swarm contracts, default JSON configuration, route validation, runtime route events, chief auditor final gate, and local UI endpoints. The UI must read contract JSON and persisted audit data rather than inventing a separate runtime model.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy, Alembic, PostgreSQL 16, pgvector Docker image, pytest.

---

## File Structure

- `docker-compose.yml`: switch local Postgres image from `postgres:16-alpine` to `pgvector/pgvector:pg16`.
- `alembic/versions/0002_enable_pgvector.py`: enable the `vector` extension for PostgreSQL deployments while no-oping on SQLite.
- `tests/triada/test_pgvector_config.py`: verify Docker Compose and migration configuration.
- `app/contracts/roles.py`: keep existing role/handoff contracts and reuse `ContractRef`.
- `app/contracts/swarm.py`: define swarm topology, worker-auditor pairs, route map, scaling rules, invariants, and upgrade policy.
- `app/contracts/default_swarm_contract.json`: default `swarm_contract@1.0`.
- `app/contracts/loader.py`: load and validate swarm contracts from JSON.
- `tests/triada/test_swarm_contracts.py`: validate topology, pair rules, audit gates, scaling, and upgrades.
- `app/services/execution_engine.py`: load contract, emit route events, enforce chief auditor gate.
- `tests/triada/test_execution_engine_swarm.py`: verify route events and no final output before audit gates.
- `app/audit/projection.py`: add graph-friendly route projection helpers.
- `app/api/routes.py`: add contract, route graph, and privileged raw reasoning endpoints.
- `tests/triada/test_api_swarm_ui.py`: verify local UI data endpoints.
- `README.md`: document pgvector setup and swarm contract endpoints.

## Task 1: Enable Pgvector Locally

**Files:**
- Modify: `docker-compose.yml`
- Create: `alembic/versions/0002_enable_pgvector.py`
- Create: `tests/triada/test_pgvector_config.py`
- Modify: `README.md`

- [ ] **Step 1: Write failing tests**

Create `tests/triada/test_pgvector_config.py`:

```python
from pathlib import Path


def test_docker_compose_uses_pgvector_image():
    compose = Path("docker-compose.yml").read_text()

    assert "image: pgvector/pgvector:pg16" in compose
    assert "postgres:16-alpine" not in compose


def test_pgvector_migration_is_postgres_guarded():
    migration = Path("alembic/versions/0002_enable_pgvector.py").read_text()

    assert "CREATE EXTENSION IF NOT EXISTS vector" in migration
    assert 'bind.dialect.name != "postgresql"' in migration
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
python3 -m pytest tests/triada/test_pgvector_config.py -q
```

Expected: FAIL because the migration does not exist and Docker Compose still uses `postgres:16-alpine`.

- [ ] **Step 3: Update Docker Compose**

In `docker-compose.yml`, change:

```yaml
  postgres:
    image: postgres:16-alpine
```

to:

```yaml
  postgres:
    image: pgvector/pgvector:pg16
```

- [ ] **Step 4: Add Alembic migration**

Create `alembic/versions/0002_enable_pgvector.py`:

```python
from alembic import op


revision = "0002_enable_pgvector"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP EXTENSION IF EXISTS vector")
```

- [ ] **Step 5: Document pgvector**

Add to `README.md` PostgreSQL section:

```markdown
The local PostgreSQL container uses `pgvector/pgvector:pg16`, so TRIADA can store
future embedding vectors in the same database. Alembic migration
`0002_enable_pgvector` enables the `vector` extension for PostgreSQL and skips
the extension on SQLite.
```

- [ ] **Step 6: Verify**

Run:

```bash
python3 -m pytest tests/triada/test_pgvector_config.py -q
python3 -m pytest -q
```

Expected: both commands pass.

- [ ] **Step 7: Commit**

```bash
git add docker-compose.yml alembic/versions/0002_enable_pgvector.py tests/triada/test_pgvector_config.py README.md
git commit -m "chore: enable pgvector for local postgres"
```

## Task 2: Add Swarm Contract Models

**Files:**
- Create: `app/contracts/swarm.py`
- Create: `tests/triada/test_swarm_contracts.py`

- [ ] **Step 1: Write failing tests**

Create `tests/triada/test_swarm_contracts.py`:

```python
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
            TaskWeightRule(weight="small", max_steps=1, risk_policies=[RiskPolicy.READ_ONLY], worker_auditor_pairs=3),
            TaskWeightRule(weight="large", min_steps=6, worker_auditor_pairs=5),
        ],
    )


def test_valid_swarm_contract_has_minimum_three_worker_auditor_pairs():
    contract = _valid_contract()

    assert len(contract.worker_auditor_pairs) == 3
    assert contract.worker_auditor_pairs[0].worker_id == "worker-1"
    assert contract.worker_auditor_pairs[0].auditor_id == "auditor-1"


def test_swarm_contract_rejects_less_than_three_pairs():
    with pytest.raises(ValidationError):
        _valid_contract().model_copy(update={"worker_auditor_pairs": []}, deep=True).model_validate(
            {
                **_valid_contract().model_dump(mode="python"),
                "worker_auditor_pairs": [
                    {"worker_id": "worker-1", "auditor_id": "auditor-1"},
                    {"worker_id": "worker-2", "auditor_id": "auditor-2"},
                ],
            }
        )


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
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
python3 -m pytest tests/triada/test_swarm_contracts.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.contracts.swarm'`.

- [ ] **Step 3: Implement swarm contract models**

Create `app/contracts/swarm.py`:

```python
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
    chief_auditor: ChiefAuditor = ChiefAuditor(agent_id="chief-auditor")
    min_worker_auditor_pairs: int = Field(default=3, ge=3)


class SwarmScaling(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_pairs: int = Field(default=3, ge=3)
    min_pairs: int = Field(default=3, ge=3)
    max_pairs: int = Field(default=12, ge=3)
    scale_by: list[str] = Field(default_factory=lambda: ["task_weight", "step_count", "risk_policy", "tool_risk"])

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
    human_output_contract: ContractRef = ContractRef(name="human_review_packet")

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
        if self.topology.chief_auditor.agent_id in worker_ids or self.topology.chief_auditor.agent_id in auditor_ids:
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
            raise ValueError(f"missing required swarm routes: {sorted(str(route) for route in missing_routes)}")
        for route in self.route_map:
            if route.source == AgentEndpoint.WORKER and route.target == AgentEndpoint.HUMAN:
                raise ValueError("worker cannot route directly to human")
        for rule in self.task_weight_rules:
            if rule.worker_auditor_pairs > self.swarm_scaling.max_pairs:
                raise ValueError("task weight rule exceeds swarm scaling max_pairs")
        return self
```

- [ ] **Step 4: Run tests**

Run:

```bash
python3 -m pytest tests/triada/test_swarm_contracts.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/contracts/swarm.py tests/triada/test_swarm_contracts.py
git commit -m "feat: add swarm contract models"
```

## Task 3: Add Default Swarm Contract JSON And Loader

**Files:**
- Create: `app/contracts/default_swarm_contract.json`
- Create: `app/contracts/loader.py`
- Modify: `app/contracts/__init__.py`
- Create: `tests/triada/test_swarm_contract_loader.py`

- [ ] **Step 1: Write failing loader tests**

Create `tests/triada/test_swarm_contract_loader.py`:

```python
from pathlib import Path

from app.contracts.loader import load_default_swarm_contract, load_swarm_contract
from app.contracts.swarm import AgentEndpoint


def test_load_default_swarm_contract():
    contract = load_default_swarm_contract()

    assert len(contract.worker_auditor_pairs) == 3
    assert contract.swarm_scaling.default_pairs == 3
    assert any(
        route.source == AgentEndpoint.WORKER and route.target == AgentEndpoint.ASSIGNED_AUDITOR
        for route in contract.route_map
    )


def test_load_swarm_contract_from_json_path(tmp_path: Path):
    source = Path("app/contracts/default_swarm_contract.json")
    target = tmp_path / "swarm.json"
    target.write_text(source.read_text())

    contract = load_swarm_contract(target)

    assert contract.contract_version == "1.0"
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
python3 -m pytest tests/triada/test_swarm_contract_loader.py -q
```

Expected: FAIL because loader and JSON do not exist.

- [ ] **Step 3: Add default JSON**

Create `app/contracts/default_swarm_contract.json` with a valid three-pair contract:

```json
{
  "schema_version": "1.0",
  "contract_version": "1.0",
  "topology": {
    "orchestrator_id": "orchestrator",
    "chief_auditor": {"agent_id": "chief-auditor", "strict_mode": false},
    "min_worker_auditor_pairs": 3
  },
  "worker_auditor_pairs": [
    {"worker_id": "worker-1", "auditor_id": "auditor-1", "capabilities": ["read_only_tools"], "max_parallel_steps": 1},
    {"worker_id": "worker-2", "auditor_id": "auditor-2", "capabilities": ["read_only_tools"], "max_parallel_steps": 1},
    {"worker_id": "worker-3", "auditor_id": "auditor-3", "capabilities": ["read_only_tools"], "max_parallel_steps": 1}
  ],
  "swarm_scaling": {
    "default_pairs": 3,
    "min_pairs": 3,
    "max_pairs": 12,
    "scale_by": ["task_weight", "step_count", "risk_policy", "tool_risk"]
  },
  "route_map": [
    {"source": "human", "target": "orchestrator", "reason": "create_task", "input_contract": {"name": "task_request", "version": "1.0"}, "output_contract": {"name": "task_plan_request", "version": "1.0"}, "required_events": ["task_created"]},
    {"source": "orchestrator", "target": "worker", "reason": "assign_step", "input_contract": {"name": "worker_assignment", "version": "1.0"}, "output_contract": {"name": "worker_result", "version": "1.0"}, "required_events": ["worker_step_started"]},
    {"source": "worker", "target": "assigned_auditor", "reason": "submit_evidence", "input_contract": {"name": "worker_result", "version": "1.0"}, "output_contract": {"name": "audit_verdict", "version": "1.0"}, "required_events": ["worker_step_completed", "audit_verdict"]},
    {"source": "assigned_auditor", "target": "worker", "reason": "request_correction", "input_contract": {"name": "audit_correction", "version": "1.0"}, "output_contract": {"name": "worker_result", "version": "1.0"}, "required_events": ["audit_verdict"]},
    {"source": "assigned_auditor", "target": "chief_auditor", "reason": "escalate_verdict", "input_contract": {"name": "audit_verdict", "version": "1.0"}, "output_contract": {"name": "chief_audit_verdict", "version": "1.0"}, "required_events": ["audit_verdict"]},
    {"source": "chief_auditor", "target": "orchestrator", "reason": "return_final_gate", "input_contract": {"name": "chief_audit_verdict", "version": "1.0"}, "output_contract": {"name": "human_review_packet", "version": "1.0"}, "required_events": ["chief_audit_verdict"]},
    {"source": "orchestrator", "target": "human", "reason": "deliver_human_packet", "input_contract": {"name": "human_review_packet", "version": "1.0"}, "output_contract": {"name": "human_decision", "version": "1.0"}, "required_events": ["human_review_packet_created"]}
  ],
  "task_weight_rules": [
    {"weight": "small", "max_steps": 1, "risk_policies": ["read_only"], "worker_auditor_pairs": 3},
    {"weight": "medium", "max_steps": 5, "worker_auditor_pairs": 3},
    {"weight": "large", "min_steps": 6, "worker_auditor_pairs": 5},
    {"weight": "critical", "risk_policies": ["write", "destructive"], "worker_auditor_pairs": 3, "requires_chief_auditor_strict_mode": true}
  ],
  "upgrade_policy": {
    "allow_minor_upgrade": true,
    "breaking_changes_require": "new_major_version",
    "migration_required_for": ["route_removed", "required_field_removed", "audit_gate_weakened", "worker_auditor_pairing_changed"],
    "forbidden_without_explicit_approval": ["remove_assigned_auditor", "allow_worker_to_human_route", "allow_orchestrator_final_without_chief_audit"]
  },
  "human_output_contract": {"name": "human_review_packet", "version": "1.0"}
}
```

- [ ] **Step 4: Add loader**

Create `app/contracts/loader.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from app.contracts.swarm import SwarmContract


DEFAULT_SWARM_CONTRACT_PATH = Path(__file__).with_name("default_swarm_contract.json")


def load_swarm_contract(path: str | Path) -> SwarmContract:
    payload = json.loads(Path(path).read_text())
    return SwarmContract.model_validate(payload)


def load_default_swarm_contract() -> SwarmContract:
    return load_swarm_contract(DEFAULT_SWARM_CONTRACT_PATH)
```

Update `app/contracts/__init__.py`:

```python
"""Machine-checkable TRIADA contracts."""
```

- [ ] **Step 5: Run tests**

Run:

```bash
python3 -m pytest tests/triada/test_swarm_contract_loader.py tests/triada/test_swarm_contracts.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/contracts/default_swarm_contract.json app/contracts/loader.py app/contracts/__init__.py tests/triada/test_swarm_contract_loader.py
git commit -m "feat: add default swarm contract loader"
```

## Task 4: Emit Runtime Route Events

**Files:**
- Modify: `app/services/execution_engine.py`
- Create: `tests/triada/test_execution_engine_swarm.py`

- [ ] **Step 1: Write failing route event test**

Create `tests/triada/test_execution_engine_swarm.py` using the same fake service patterns as `tests/triada/test_execution_engine_runtime.py`:

```python
import pytest

from app.events.models import AuditEvent


@pytest.mark.asyncio
async def test_execution_engine_emits_swarm_route_events(task_service):
    task = await task_service.create_task(
        goal="inspect repository status",
        allowed_tools=["git"],
        acceptance_criteria=["return git status"],
    )

    await task_service.run_task_once(task.id)
    events = await task_service.event_repository.list_events(task.trace_id)
    route_events = [event for event in events if event.event_type == "swarm_route_selected"]

    assert route_events
    assert any(event.payload["reason"] == "assign_step" for event in route_events)
    assert any(event.payload["reason"] == "submit_evidence" for event in route_events)
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
python3 -m pytest tests/triada/test_execution_engine_swarm.py -q
```

Expected: FAIL because `swarm_route_selected` is not emitted.

- [ ] **Step 3: Load contract and emit route events**

In `ExecutionEngine.__init__`, add:

```python
from app.contracts.loader import load_default_swarm_contract

self._swarm_contract = load_default_swarm_contract()
self._worker_auditor_pairs = self._swarm_contract.worker_auditor_pairs
```

Add helper:

```python
async def _emit_route(
    self,
    task: Any,
    *,
    source: str,
    target: str,
    reason: str,
    input_contract: str,
    output_contract: str,
    agent_id: str | None = None,
) -> None:
    await self._emit(
        task,
        "swarm_route_selected",
        {
            "schema_version": "1.0",
            "source": source,
            "target": target,
            "reason": reason,
            "input_contract": input_contract,
            "output_contract": output_contract,
        },
        agent_id=agent_id,
    )
```

Call `_emit_route` before worker assignment and before auditor submission.

- [ ] **Step 4: Run tests**

Run:

```bash
python3 -m pytest tests/triada/test_execution_engine_swarm.py tests/triada/test_execution_engine_runtime.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/execution_engine.py tests/triada/test_execution_engine_swarm.py
git commit -m "feat: emit swarm route events"
```

## Task 5: Add Chief Auditor Gate And Human Review Packet

**Files:**
- Modify: `app/services/execution_engine.py`
- Modify: `app/events/models.py` if a typed event model is needed
- Modify: `tests/triada/test_execution_engine_swarm.py`

- [ ] **Step 1: Add failing final gate test**

Append to `tests/triada/test_execution_engine_swarm.py`:

```python
@pytest.mark.asyncio
async def test_execution_engine_emits_chief_auditor_gate_before_human_packet(task_service):
    task = await task_service.create_task(
        goal="inspect repository status",
        allowed_tools=["git"],
        acceptance_criteria=["return git status"],
    )

    await task_service.run_task_once(task.id)
    events = await task_service.event_repository.list_events(task.trace_id)
    event_types = [event.event_type for event in events]

    assert "chief_audit_verdict" in event_types
    assert "human_review_packet_created" in event_types
    assert event_types.index("chief_audit_verdict") < event_types.index("human_review_packet_created")
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
python3 -m pytest tests/triada/test_execution_engine_swarm.py::test_execution_engine_emits_chief_auditor_gate_before_human_packet -q
```

Expected: FAIL because the chief auditor gate and human packet events do not exist.

- [ ] **Step 3: Emit chief auditor verdict after assigned auditor verdict**

After `audit_verdict`, emit:

```python
await self._emit(
    task,
    "chief_audit_verdict",
    {
        "schema_version": "1.0",
        "chief_auditor_id": self._swarm_contract.topology.chief_auditor.agent_id,
        "verdict": verdict.verdict.value,
        "source_verdict_refs": ["audit_verdict"],
        "summary": verdict.summary,
    },
    agent_id=self._swarm_contract.topology.chief_auditor.agent_id,
)
```

- [ ] **Step 4: Emit human review packet after chief gate**

Emit:

```python
await self._emit(
    task,
    "human_review_packet_created",
    {
        "schema_version": "1.0",
        "contract": {"name": "human_review_packet", "version": "1.0"},
        "status": final_status,
        "chief_auditor_verdict": verdict.verdict.value,
        "summary": verdict.summary,
        "worker_result_count": len(worker_results),
        "tool_result_count": len(tool_records),
        "raw_reasoning_refs": [],
    },
    agent_id="orchestrator",
)
```

- [ ] **Step 5: Run tests**

Run:

```bash
python3 -m pytest tests/triada/test_execution_engine_swarm.py tests/triada/test_agents_auditor.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/services/execution_engine.py tests/triada/test_execution_engine_swarm.py
git commit -m "feat: add chief auditor final gate"
```

## Task 6: Add Swarm UI Data Endpoints

**Files:**
- Modify: `app/audit/projection.py`
- Modify: `app/api/routes.py`
- Create: `tests/triada/test_api_swarm_ui.py`

- [ ] **Step 1: Write failing API tests**

Create `tests/triada/test_api_swarm_ui.py`:

```python
import pytest


@pytest.mark.asyncio
async def test_get_swarm_contract(client):
    response = await client.get("/v1/swarm/contract")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "1.0"
    assert len(payload["worker_auditor_pairs"]) >= 3


@pytest.mark.asyncio
async def test_get_task_route_graph(client):
    created = await client.post(
        "/v1/tasks",
        json={
            "goal": "inspect repository status",
            "allowed_tools": ["git"],
            "acceptance_criteria": ["return git status"],
        },
    )
    task_id = created.json()["task_id"]

    await client.post(f"/v1/tasks/{task_id}/run_once")
    response = await client.get(f"/v1/tasks/{task_id}/swarm-graph")

    assert response.status_code == 200
    payload = response.json()
    assert payload["nodes"]
    assert payload["edges"]
    assert any(edge["reason"] == "assign_step" for edge in payload["edges"])
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
python3 -m pytest tests/triada/test_api_swarm_ui.py -q
```

Expected: FAIL because endpoints do not exist.

- [ ] **Step 3: Add route projection helper**

In `app/audit/projection.py`, add:

```python
def swarm_graph_from_events(events) -> dict:
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    for event in events:
        if event.event_type != "swarm_route_selected":
            continue
        source = event.payload["source"]
        target = event.payload["target"]
        nodes[source] = {"id": source}
        nodes[target] = {"id": target}
        edges.append(
            {
                "id": str(event.id),
                "source": source,
                "target": target,
                "reason": event.payload["reason"],
                "input_contract": event.payload["input_contract"],
                "output_contract": event.payload["output_contract"],
                "sequence": event.sequence,
            }
        )
    return {"nodes": list(nodes.values()), "edges": edges}
```

- [ ] **Step 4: Add API endpoints**

In `app/api/routes.py`, import:

```python
from app.audit.projection import swarm_graph_from_events
from app.contracts.loader import load_default_swarm_contract
```

Add endpoints:

```python
@router.get("/swarm/contract")
async def get_swarm_contract() -> dict:
    return load_default_swarm_contract().model_dump(mode="json")


@router.get("/tasks/{task_id}/swarm-graph")
async def get_task_swarm_graph(task_id: UUID, request: Request) -> dict:
    task = await _get_task_or_404(task_id, request)
    events = await request.app.state.event_repository.list_events(task.trace_id)
    return swarm_graph_from_events(events)
```

- [ ] **Step 5: Run tests**

Run:

```bash
python3 -m pytest tests/triada/test_api_swarm_ui.py tests/triada/test_api_sse.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/audit/projection.py app/api/routes.py tests/triada/test_api_swarm_ui.py
git commit -m "feat: expose swarm graph endpoints"
```

## Task 7: Build Minimal Local Swarm UI

**Files:**
- Create: `app/ui/index.html`
- Modify: `app/main.py`
- Create: `tests/triada/test_local_ui.py`

- [ ] **Step 1: Write failing UI test**

Create `tests/triada/test_local_ui.py`:

```python
import pytest


@pytest.mark.asyncio
async def test_local_ui_serves_swarm_dashboard(client):
    response = await client.get("/ui")

    assert response.status_code == 200
    assert "TRIADA Swarm" in response.text
    assert "/v1/swarm/contract" in response.text
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
python3 -m pytest tests/triada/test_local_ui.py -q
```

Expected: FAIL with 404.

- [ ] **Step 3: Add static UI HTML**

Create `app/ui/index.html` with a compact dashboard that fetches:

```javascript
const contract = await fetch("/v1/swarm/contract").then((r) => r.json());
```

The first screen must include:

```html
<h1>TRIADA Swarm</h1>
<section id="graph"></section>
<section id="contracts"></section>
<section id="thinking"></section>
```

- [ ] **Step 4: Serve UI from FastAPI**

In `app/main.py`, add a `GET /ui` route or mount static files so `/ui` returns `app/ui/index.html`.

- [ ] **Step 5: Run tests**

Run:

```bash
python3 -m pytest tests/triada/test_local_ui.py tests/triada/test_api_swarm_ui.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/ui/index.html app/main.py tests/triada/test_local_ui.py
git commit -m "feat: add local swarm dashboard"
```

## Task 8: Final Verification And Docs

**Files:**
- Modify: `README.md`
- Modify: `ROLE_CONTRACTS.md`

- [ ] **Step 1: Update docs with endpoints**

Document:

```text
GET /v1/swarm/contract
GET /v1/tasks/{task_id}/swarm-graph
GET /ui
```

- [ ] **Step 2: Run full verification**

Run:

```bash
python3 -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 3: Optional local Postgres verification**

Run:

```bash
TRIADA_POSTGRES_PORT=5433 docker compose up -d postgres
export DATABASE_URL=postgresql+asyncpg://triada:triada@127.0.0.1:5433/triada
alembic upgrade head
psql postgresql://triada:triada@127.0.0.1:5433/triada -c "select extname from pg_extension where extname = 'vector';"
```

Expected:

```text
 extname
---------
 vector
```

- [ ] **Step 4: Commit docs**

```bash
git add README.md ROLE_CONTRACTS.md
git commit -m "docs: document swarm contracts and pgvector"
```

## Self-Review

- Spec coverage: pgvector support, swarm topology, worker-auditor pairing,
  route map, task weight scaling, audit bypass prevention, human output, upgrade
  policy, and local UI are all mapped to tasks.
- Scope split: the plan keeps contract/runtime work before UI, while pgvector is
  isolated as the first infrastructure task.
- Type consistency: `SwarmContract`, `WorkerAuditorPair`, `RouteMapEntry`,
  `AgentEndpoint`, and endpoint names are consistent across tasks.
- No placeholders: all code-oriented steps include concrete file paths,
  commands, and expected results.
