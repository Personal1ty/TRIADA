# DevOps Multiagent Framework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the MVP Core Framework First version of the TRIADA DevOps multiagent orchestration system.

**Architecture:** The implementation is layered around append-only audit events: schemas and redaction first, persistence and event emission second, agents/tools third, API/SSE/CLI last. All runtime facts are persisted before publication; `thinking_summary_delta` is telemetry, not evidence. `FakeLLMProvider` powers tests while `OpenAICompatibleProvider` supports local endpoints and FixMost/corp-coder profile at runtime.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.x, Alembic, SQLite for tests, PostgreSQL for Docker Compose, asyncio, httpx, pytest, pytest-asyncio, Server-Sent Events.

---

## File Structure

Create or modify these files:

- Create `pyproject.toml`: package metadata, dependencies, pytest config.
- Create `alembic.ini`, `alembic/env.py`, `alembic/versions/0001_initial.py`: migrations.
- Create `app/__init__.py`, `app/main.py`, `app/cli.py`: application entrypoints.
- Create `app/config.py`: env-driven settings and provider selection.
- Create `app/schemas/enums.py`: task, worker, verdict, risk, event enums.
- Create `app/schemas/tasks.py`: task API request/response models.
- Create `app/events/models.py`: audit events, tool events, deltas, artifacts, verdict schemas.
- Create `app/audit/redaction.py`: secret detection/redaction.
- Create `app/audit/validator.py`: sequence, hash-chain, state, delta, and audit rule validation.
- Create `app/audit/repository.py`: persisted event queries and projections.
- Create `app/audit/emitter.py`: persist-first event emitter.
- Create `app/audit/projection.py`: conversion from events to API/SSE views.
- Create `app/persistence/session.py`: engine/session factory.
- Create `app/persistence/models.py`: SQLAlchemy tables.
- Create `app/events/bus.py`: async in-process event bus for SSE listeners.
- Create `app/llm/base.py`, `app/llm/fake.py`, `app/llm/openai_compatible.py`: provider contracts.
- Create `app/tools/base.py`, `app/tools/shell.py`, `app/tools/filesystem.py`, `app/tools/git.py`, `app/tools/terraform.py`, `app/tools/kubernetes.py`, `app/tools/docker.py`: tool adapters.
- Create `app/agents/orchestrator.py`, `app/agents/worker.py`, `app/agents/auditor.py`: agent logic.
- Create `app/services/task_service.py`, `app/services/heartbeat.py`, `app/services/execution_supervisor.py`: runtime services.
- Create `app/api/routes.py`: FastAPI routes.
- Create docs: `README.md`, `ARCHITECTURE.md`, `SECURITY.md`, `AUDIT_MODEL.md`, `EVENT_SCHEMA.md`, `LONG_RUNNING_TASKS.md`, `DEVOPS_TOOLS.md`, `AGENTS.md`, `.env.example`, `docker-compose.yml`.
- Create tests under `tests/triada/` for schemas, redaction, persistence, emitter, providers, tools, agents, API/SSE, CLI, and long-running simulation.

Keep existing FixMost files for compatibility unless a later task explicitly moves them.

---

## Task 1: Project Packaging And Settings

**Files:**
- Create: `pyproject.toml`
- Create: `app/__init__.py`
- Create: `app/config.py`
- Test: `tests/triada/test_config.py`

- [ ] **Step 1: Write failing config tests**

Create `tests/triada/test_config.py`:

```python
import pytest

from app.config import Settings, get_settings


def test_default_settings_use_fake_provider(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    settings = Settings()
    assert settings.llm_provider == "fake"
    assert settings.capture_reasoning_summary is True
    assert settings.pass_reasoning_summary_to_auditor is True


def test_api_key_is_secret_and_not_in_repr(monkeypatch):
    settings = Settings(llm_api_key="sk-secret-value")
    assert "sk-secret-value" not in repr(settings)


def test_get_settings_reads_environment(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("LLM_MODEL", "corp-coder")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.llm_provider == "openai-compatible"
    assert settings.llm_model == "corp-coder"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/triada/test_config.py -q
```

Expected: FAIL because `app.config` does not exist.

- [ ] **Step 3: Add packaging and settings**

Create `pyproject.toml` with dependencies:

```toml
[project]
name = "triada"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.111",
  "uvicorn>=0.30",
  "pydantic>=2.7",
  "pydantic-settings>=2.3",
  "sqlalchemy>=2.0",
  "alembic>=1.13",
  "aiosqlite>=0.20",
  "asyncpg>=0.29",
  "httpx>=0.27",
  "python-dotenv>=1.0",
]

[project.optional-dependencies]
test = [
  "pytest>=8.2",
  "pytest-asyncio>=0.23",
  "httpx>=0.27",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["."]
```

Create `app/__init__.py`:

```python
__all__ = ["__version__"]

__version__ = "0.1.0"
```

Create `app/config.py`:

```python
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_provider: Literal["fake", "openai-compatible"] = "fake"
    llm_base_url: str | None = None
    llm_api_key: SecretStr | None = None
    llm_model: str = "fake-devops-model"
    database_url: str = "sqlite+aiosqlite:///./triada.db"
    redis_url: str | None = None
    capture_reasoning_summary: bool = True
    pass_reasoning_summary_to_auditor: bool = True
    event_output_dir: str = ".triada/artifacts"
    shell_timeout_seconds: int = Field(default=60, ge=1, le=3600)
    max_tool_output_bytes: int = Field(default=65536, ge=1024)


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: Run config tests**

Run:

```bash
pytest tests/triada/test_config.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add pyproject.toml app/__init__.py app/config.py tests/triada/test_config.py
git commit -m "chore: add triada package settings"
```

---

## Task 2: Core Schemas And Redaction

**Files:**
- Create: `app/schemas/enums.py`
- Create: `app/events/models.py`
- Create: `app/audit/redaction.py`
- Test: `tests/triada/test_schemas_redaction.py`

- [ ] **Step 1: Write failing schema/redaction tests**

Create `tests/triada/test_schemas_redaction.py`:

```python
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.audit.redaction import contains_secret, redact_text
from app.events.models import ThinkingSummaryDelta


def make_delta(**overrides):
    base = {
        "schema_version": "1.0",
        "event_id": uuid4(),
        "trace_id": uuid4(),
        "task_id": uuid4(),
        "span_id": uuid4(),
        "parent_span_id": None,
        "agent_id": "worker-1",
        "agent_role": "worker",
        "source": "runtime",
        "sequence": 1,
        "stage": "validation",
        "action": "check",
        "summary": "Checking runtime result.",
        "observations": ["Command completed with exit code 0."],
        "input_refs": ["event:1"],
        "output_refs": [],
        "next_step": "Audit result",
        "progress_percent": 50,
        "confidence": 0.8,
        "created_at": datetime.now(UTC),
        "metadata": {},
    }
    base.update(overrides)
    return ThinkingSummaryDelta(**base)


def test_thinking_summary_delta_rejects_extra_fields():
    with pytest.raises(ValidationError):
        make_delta(extra_field="not allowed")


def test_thinking_summary_delta_rejects_hidden_reasoning_phrase():
    with pytest.raises(ValidationError):
        make_delta(summary="Let me think step by step about hidden reasoning.")


def test_thinking_summary_delta_rejects_secret_text():
    with pytest.raises(ValidationError):
        make_delta(summary="Authorization: Bearer sk-secret")


def test_redact_text_masks_common_secret_patterns():
    text = "password=my-pass Authorization: Bearer sk-token"
    redacted = redact_text(text)
    assert "my-pass" not in redacted
    assert "sk-token" not in redacted
    assert "[REDACTED]" in redacted


def test_contains_secret_detects_private_key_marker():
    assert contains_secret("-----BEGIN PRIVATE KEY-----\nabc")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/triada/test_schemas_redaction.py -q
```

Expected: FAIL because schema/redaction modules do not exist.

- [ ] **Step 3: Implement enums**

Create `app/schemas/enums.py` with string enums for:

```python
from enum import StrEnum


class AgentRole(StrEnum):
    ORCHESTRATOR = "orchestrator"
    WORKER = "worker"
    AUDITOR = "auditor"


class DeltaSource(StrEnum):
    RUNTIME = "runtime"
    MODEL = "model"


class TaskState(StrEnum):
    CREATED = "created"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    RUNNING = "running"
    VALIDATING = "validating"
    CORRECTIONS_REQUIRED = "corrections_required"
    RETRYING = "retrying"
    ROLLING_BACK = "rolling_back"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class WorkerState(StrEnum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    RUNNING = "running"
    WAITING = "waiting"
    VALIDATING = "validating"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    STALLED = "stalled"
    CANCELLED = "cancelled"


class RiskPolicy(StrEnum):
    READ_ONLY = "read_only"
    LOW_RISK_WRITE = "low_risk_write"
    HIGH_RISK_WRITE = "high_risk_write"
    DESTRUCTIVE = "destructive"


class AuditVerdictValue(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    CORRECTIONS_REQUIRED = "corrections_required"
    BLOCKED = "blocked"
```

- [ ] **Step 4: Implement redaction**

Create `app/audit/redaction.py` with compiled regex patterns for passwords, tokens, Authorization headers, private keys, and OpenAI-style keys. Public functions:

```python
def redact_text(value: str) -> str: ...
def contains_secret(value: str) -> bool: ...
def redact_payload(payload: object) -> object: ...
```

`redact_payload` must recursively process dict/list/tuple/string values and leave scalar non-strings unchanged.

- [ ] **Step 5: Implement event models**

Create `app/events/models.py` with Pydantic v2 models:

- `ThinkingSummaryDelta`
- `AuditEventCreate`
- `ToolExecutionRecord`
- `ArtifactRecord`
- `ValidationResultRecord`
- `AuditViolation`
- `AuditVerdict`

`ThinkingSummaryDelta` must set `model_config = ConfigDict(extra="forbid")` and validators for length, unsafe phrases, and secret detection.

- [ ] **Step 6: Run schema/redaction tests**

Run:

```bash
pytest tests/triada/test_schemas_redaction.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add app/schemas/enums.py app/events/models.py app/audit/redaction.py tests/triada/test_schemas_redaction.py
git commit -m "feat: add event schemas and redaction"
```

---

## Task 3: Persistence, Alembic, And Hash Chain

**Files:**
- Create: `app/persistence/session.py`
- Create: `app/persistence/models.py`
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/versions/0001_initial.py`
- Test: `tests/triada/test_persistence_hash_chain.py`

- [ ] **Step 1: Write failing persistence tests**

Create `tests/triada/test_persistence_hash_chain.py`:

```python
from uuid import uuid4

import pytest

from app.audit.repository import AuditEventRepository
from app.persistence.session import create_session_factory


@pytest.mark.asyncio
async def test_audit_events_are_hash_chained(tmp_path):
    session_factory = create_session_factory(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    repo = AuditEventRepository(session_factory)
    trace_id = uuid4()
    task_id = uuid4()

    first = await repo.append_event(
        event_type="task_created",
        trace_id=trace_id,
        task_id=task_id,
        agent_id="orchestrator",
        payload={"status": "created"},
    )
    second = await repo.append_event(
        event_type="planning_started",
        trace_id=trace_id,
        task_id=task_id,
        agent_id="orchestrator",
        payload={"status": "planning"},
    )

    assert first.previous_hash == ""
    assert second.previous_hash == first.event_hash
    assert await repo.verify_trace(trace_id) is True


@pytest.mark.asyncio
async def test_duplicate_event_id_is_rejected(tmp_path):
    session_factory = create_session_factory(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    repo = AuditEventRepository(session_factory)
    event_id = uuid4()
    trace_id = uuid4()
    task_id = uuid4()

    await repo.append_event(
        id=event_id,
        event_type="task_created",
        trace_id=trace_id,
        task_id=task_id,
        agent_id="orchestrator",
        payload={},
    )

    with pytest.raises(ValueError, match="duplicate event"):
        await repo.append_event(
            id=event_id,
            event_type="task_created",
            trace_id=trace_id,
            task_id=task_id,
            agent_id="orchestrator",
            payload={},
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/triada/test_persistence_hash_chain.py -q
```

Expected: FAIL because persistence/repository modules do not exist.

- [ ] **Step 3: Implement SQLAlchemy models and session**

Create `app/persistence/session.py`:

```python
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def create_session_factory(database_url: str) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(database_url, future=True)
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    from app.config import get_settings

    factory = create_session_factory(get_settings().database_url)
    async with factory() as session:
        yield session
```

Create `app/persistence/models.py` with SQLAlchemy declarative models for all MVP tables in the spec. Include indexes on `trace_id, created_at`, `task_id, created_at`, `agent_id, sequence`, `event_type`, `stage`, `source`, and `status`.

- [ ] **Step 4: Implement repository and hash utilities**

Create `app/audit/repository.py` with:

- `canonical_json(payload: object) -> str`
- `compute_event_hash(event_dict: dict[str, object], previous_hash: str) -> str`
- `AuditEventRepository.append_event(...)`
- `AuditEventRepository.list_events(trace_id, after_event_id=None)`
- `AuditEventRepository.verify_trace(trace_id) -> bool`

`append_event` must create tables for SQLite test databases before insert by calling `Base.metadata.create_all` through the session engine.

- [ ] **Step 5: Add Alembic migration**

Create `alembic.ini`, `alembic/env.py`, and `alembic/versions/0001_initial.py`. The migration must create the same MVP tables as SQLAlchemy models.

- [ ] **Step 6: Run persistence tests**

Run:

```bash
pytest tests/triada/test_persistence_hash_chain.py -q
```

Expected: PASS.

- [ ] **Step 7: Run migration on local SQLite**

Run:

```bash
DATABASE_URL=sqlite+aiosqlite:///./triada-plan-check.db alembic upgrade head
```

Expected: migration completes without errors.

- [ ] **Step 8: Commit**

Run:

```bash
git add app/persistence app/audit/repository.py alembic.ini alembic tests/triada/test_persistence_hash_chain.py
git commit -m "feat: add persistence and audit hash chain"
```

---

## Task 4: Persist-First Event Emitter And Projections

**Files:**
- Create: `app/events/bus.py`
- Create: `app/audit/emitter.py`
- Create: `app/audit/projection.py`
- Test: `tests/triada/test_event_emitter.py`

- [ ] **Step 1: Write failing emitter tests**

Create `tests/triada/test_event_emitter.py`:

```python
from uuid import uuid4

import pytest

from app.audit.emitter import AuditEmitter
from app.audit.repository import AuditEventRepository
from app.events.bus import InMemoryEventBus
from app.persistence.session import create_session_factory


@pytest.mark.asyncio
async def test_emitter_persists_before_publish(tmp_path):
    session_factory = create_session_factory(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    repo = AuditEventRepository(session_factory)
    bus = InMemoryEventBus()
    emitter = AuditEmitter(repo, bus)
    trace_id = uuid4()
    task_id = uuid4()

    event = await emitter.emit(
        event_type="task_created",
        trace_id=trace_id,
        task_id=task_id,
        agent_id="orchestrator",
        payload={"message": "ok"},
    )

    published = await bus.drain()
    persisted = await repo.list_events(trace_id)
    assert persisted[0].id == event.id
    assert published[0].id == event.id


@pytest.mark.asyncio
async def test_emitter_redacts_payload_before_persistence(tmp_path):
    session_factory = create_session_factory(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    repo = AuditEventRepository(session_factory)
    emitter = AuditEmitter(repo, InMemoryEventBus())

    event = await emitter.emit(
        event_type="tool_execution_completed",
        trace_id=uuid4(),
        task_id=uuid4(),
        agent_id="worker-1",
        payload={"stdout": "Authorization: Bearer sk-secret"},
    )

    assert "sk-secret" not in str(event.payload)
    assert "[REDACTED]" in str(event.payload)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/triada/test_event_emitter.py -q
```

Expected: FAIL because emitter/bus do not exist.

- [ ] **Step 3: Implement in-memory event bus**

Create `app/events/bus.py` with `InMemoryEventBus` supporting:

- `publish(event)`
- `subscribe(trace_id)` returning an async iterator queue
- `drain()` for tests
- bounded listener cleanup on cancellation

- [ ] **Step 4: Implement emitter**

Create `app/audit/emitter.py` with `AuditEmitter.emit(...)` that redacts payload, appends via repository, then publishes to bus.

- [ ] **Step 5: Implement projections**

Create `app/audit/projection.py` with functions:

- `event_to_sse(event) -> dict[str, str]`
- `events_to_public_response(events) -> list[dict]`
- `thinking_deltas_from_events(events) -> list[dict]`

- [ ] **Step 6: Run emitter tests**

Run:

```bash
pytest tests/triada/test_event_emitter.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add app/events/bus.py app/audit/emitter.py app/audit/projection.py tests/triada/test_event_emitter.py
git commit -m "feat: add persist-first event emitter"
```

---

## Task 5: LLM Providers

**Files:**
- Create: `app/llm/base.py`
- Create: `app/llm/fake.py`
- Create: `app/llm/openai_compatible.py`
- Test: `tests/triada/test_llm_providers.py`

- [ ] **Step 1: Write failing provider tests**

Create `tests/triada/test_llm_providers.py`:

```python
import pytest

from app.llm.fake import FakeLLMProvider
from app.llm.openai_compatible import OpenAICompatibleProvider


@pytest.mark.asyncio
async def test_fake_llm_is_deterministic():
    provider = FakeLLMProvider()
    first = await provider.complete_json("plan a task", schema_name="plan")
    second = await provider.complete_json("plan a task", schema_name="plan")
    assert first == second
    assert "thinking_summary_delta" in first
    assert "answer" in first


@pytest.mark.asyncio
async def test_openai_provider_requires_base_url_for_real_calls():
    provider = OpenAICompatibleProvider(base_url=None, api_key=None, model="corp-coder")
    with pytest.raises(RuntimeError, match="LLM_BASE_URL"):
        await provider.complete_json("hello", schema_name="plan")


@pytest.mark.asyncio
async def test_openai_provider_error_does_not_leak_api_key():
    provider = OpenAICompatibleProvider(
        base_url=None,
        api_key="sk-secret-token",
        model="corp-coder",
    )
    with pytest.raises(RuntimeError) as exc:
        await provider.complete_json("hello", schema_name="plan")
    assert "sk-secret-token" not in str(exc.value)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/triada/test_llm_providers.py -q
```

Expected: FAIL because provider modules do not exist.

- [ ] **Step 3: Implement provider interface**

Create `app/llm/base.py` with:

```python
from abc import ABC, abstractmethod
from typing import Any


class LLMProvider(ABC):
    @abstractmethod
    async def complete_json(self, prompt: str, *, schema_name: str) -> dict[str, Any]:
        raise NotImplementedError
```

- [ ] **Step 4: Implement FakeLLMProvider**

Create deterministic responses for `schema_name` values: `plan`, `worker_result`, `audit_verdict`, and default. Include public-safe `thinking_summary_delta` envelope.

- [ ] **Step 5: Implement OpenAICompatibleProvider**

Use `httpx.AsyncClient` to call `/chat/completions`. Include `Authorization` only when API key is configured. Do not leak API key in exceptions. Parse assistant content as JSON. Reject non-JSON content with a redacted error.

- [ ] **Step 6: Run provider tests**

Run:

```bash
pytest tests/triada/test_llm_providers.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add app/llm tests/triada/test_llm_providers.py
git commit -m "feat: add fake and openai-compatible llm providers"
```

---

## Task 6: Tool Adapter Foundation

**Files:**
- Create: `app/tools/base.py`
- Create: `app/tools/shell.py`
- Create: `app/tools/filesystem.py`
- Create: `app/tools/git.py`
- Create: `app/tools/terraform.py`
- Create: `app/tools/kubernetes.py`
- Create: `app/tools/docker.py`
- Test: `tests/triada/test_tools.py`

- [ ] **Step 1: Write failing tool tests**

Create `tests/triada/test_tools.py`:

```python
import pytest

from app.schemas.enums import RiskPolicy
from app.tools.base import ToolRequest
from app.tools.shell import ShellTool
from app.tools.terraform import TerraformPlanTool


@pytest.mark.asyncio
async def test_shell_tool_rejects_non_allowlisted_command(tmp_path):
    tool = ShellTool(allowlist={"echo"}, workspace=tmp_path)
    request = ToolRequest(command=["rm", "-rf", "/"], risk_policy=RiskPolicy.DESTRUCTIVE)
    with pytest.raises(PermissionError, match="not allowlisted"):
        await tool.execute(request)


@pytest.mark.asyncio
async def test_shell_tool_executes_allowlisted_command(tmp_path):
    tool = ShellTool(allowlist={"echo"}, workspace=tmp_path)
    result = await tool.execute(
        ToolRequest(command=["echo", "hello"], risk_policy=RiskPolicy.READ_ONLY)
    )
    assert result.exit_code == 0
    assert result.stdout.strip() == "hello"


@pytest.mark.asyncio
async def test_high_risk_requires_approval_reference(tmp_path):
    tool = ShellTool(allowlist={"echo"}, workspace=tmp_path)
    request = ToolRequest(command=["echo", "write"], risk_policy=RiskPolicy.HIGH_RISK_WRITE)
    with pytest.raises(PermissionError, match="approval"):
        await tool.execute(request)


def test_terraform_plan_tool_blocks_apply(tmp_path):
    tool = TerraformPlanTool(workspace=tmp_path)
    assert tool.is_command_allowed(["terraform", "plan"]) is True
    assert tool.is_command_allowed(["terraform", "apply"]) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/triada/test_tools.py -q
```

Expected: FAIL because tool modules do not exist.

- [ ] **Step 3: Implement base tool contract**

Create `app/tools/base.py` with:

- `ToolRequest`
- `ToolResult`
- `ToolAdapter`
- `ensure_risk_allowed(request)`

`ToolRequest` includes `command`, `working_dir`, `risk_policy`, `approval_ref`, `expected_change`, `validation_command`, and `rollback_action`.

- [ ] **Step 4: Implement ShellTool**

Use `asyncio.create_subprocess_exec`, no `shell=True`, configured workspace, command allowlist, timeout, output cap, and redaction.

- [ ] **Step 5: Implement safe adapters**

Implement:

- `FileSystemTool` with workspace path checks.
- `GitTool` for `git status`, `git diff`, `git log`.
- `TerraformPlanTool` for `terraform fmt`, `terraform validate`, `terraform plan`.
- `KubernetesReadOnlyTool` for `kubectl get`, `kubectl describe`, `kubectl logs`.
- `DockerTool` for `docker ps`, `docker images`, `docker inspect`.

Each adapter can delegate execution to `ShellTool` after command validation.

- [ ] **Step 6: Run tool tests**

Run:

```bash
pytest tests/triada/test_tools.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add app/tools tests/triada/test_tools.py
git commit -m "feat: add safe devops tool adapters"
```

---

## Task 7: Agents And Auditor Rules

**Files:**
- Create: `app/agents/orchestrator.py`
- Create: `app/agents/worker.py`
- Create: `app/agents/auditor.py`
- Create: `app/audit/validator.py`
- Test: `tests/triada/test_agents_auditor.py`

- [ ] **Step 1: Write failing agent/auditor tests**

Create `tests/triada/test_agents_auditor.py`:

```python
from uuid import uuid4

import pytest

from app.agents.auditor import Auditor
from app.agents.orchestrator import Orchestrator
from app.agents.worker import Worker
from app.events.models import ToolExecutionRecord
from app.llm.fake import FakeLLMProvider


@pytest.mark.asyncio
async def test_orchestrator_creates_plan():
    orchestrator = Orchestrator(llm=FakeLLMProvider())
    plan = await orchestrator.plan_task(
        goal="Inspect local repository",
        allowed_tools=["git"],
        acceptance_criteria=["Return git status evidence"],
    )
    assert plan.steps
    assert plan.steps[0].output_contract.required_checks


@pytest.mark.asyncio
async def test_worker_receives_one_step_and_returns_evidence(tmp_path):
    worker = Worker(worker_id="worker-1", workspace=tmp_path)
    result = await worker.run_step(
        task_id=uuid4(),
        step_id="step-1",
        title="Echo evidence",
        allowed_tools=["shell"],
        command=["echo", "evidence"],
    )
    assert result.step_id == "step-1"
    assert result.status == "success"
    assert result.evidence


def test_auditor_detects_nonzero_exit_code():
    auditor = Auditor()
    verdict = auditor.audit_tool_results(
        [
            ToolExecutionRecord(
                tool="shell",
                command=["false"],
                started_at=None,
                finished_at=None,
                exit_code=1,
                stdout_ref=None,
                stderr_ref=None,
                timed_out=False,
            )
        ],
        worker_summary="Everything succeeded.",
    )
    assert verdict.verdict == "fail"
    assert any(v.rule_id == "TOOL_FAILURE_NOT_REPORTED" for v in verdict.violations)


def test_auditor_does_not_accept_delta_as_evidence():
    auditor = Auditor()
    verdict = auditor.audit_claims(
        required_artifacts=["artifact:report"],
        artifacts=[],
        thinking_deltas=[{"summary": "Created artifact:report"}],
    )
    assert verdict.verdict in {"fail", "corrections_required"}
    assert any(v.rule_id == "REQUIRED_ARTIFACT_MISSING" for v in verdict.violations)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/triada/test_agents_auditor.py -q
```

Expected: FAIL because agents are not implemented.

- [ ] **Step 3: Implement orchestrator models and planning**

In `app/agents/orchestrator.py`, create Pydantic models:

- `StepContract`
- `PlanStep`
- `TaskPlan`

Implement `Orchestrator.plan_task(...)` using provider output when available, with deterministic fallback for FakeLLM. Risk classification can start rule-based: destructive keywords map to higher risk.

- [ ] **Step 4: Implement worker**

In `app/agents/worker.py`, create `WorkerResult` model and `Worker.run_step(...)`. For MVP, support shell echo/git status through tool registry. Ensure only the given step is processed.

- [ ] **Step 5: Implement auditor and validator**

In `app/agents/auditor.py` and `app/audit/validator.py`, implement MVP rules listed in the spec. Start with pure functions that accept records and return `AuditVerdict`.

- [ ] **Step 6: Run agent/auditor tests**

Run:

```bash
pytest tests/triada/test_agents_auditor.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add app/agents app/audit/validator.py tests/triada/test_agents_auditor.py
git commit -m "feat: add orchestrator worker and auditor"
```

---

## Task 8: Task Service, Heartbeat, Supervisor, And Long Task Simulation

**Files:**
- Create: `app/services/task_service.py`
- Create: `app/services/heartbeat.py`
- Create: `app/services/execution_supervisor.py`
- Test: `tests/triada/test_long_running.py`

- [ ] **Step 1: Write failing long-running tests**

Create `tests/triada/test_long_running.py`:

```python
import pytest

from app.services.execution_supervisor import FakeClock, LongTaskSimulator


@pytest.mark.asyncio
async def test_long_task_emits_heartbeat_and_thinking_checkpoints():
    clock = FakeClock(start=0)
    simulator = LongTaskSimulator(clock=clock, heartbeat_seconds=60, checkpoint_seconds=300)
    result = await simulator.run_virtual(duration_seconds=18 * 60, timeout_seconds=3 * 60 * 60)
    heartbeat_events = [e for e in result.events if e["event_type"] == "agent_heartbeat"]
    delta_events = [e for e in result.events if e["event_type"] == "thinking_summary_delta"]
    assert len(heartbeat_events) >= 18
    assert len(delta_events) >= 3
    assert result.status == "completed"


@pytest.mark.asyncio
async def test_timeout_triggers_cancellation():
    clock = FakeClock(start=0)
    simulator = LongTaskSimulator(clock=clock, heartbeat_seconds=60, checkpoint_seconds=300)
    result = await simulator.run_virtual(duration_seconds=4 * 60 * 60, timeout_seconds=3 * 60 * 60)
    assert result.status == "timed_out"
    assert any(e["event_type"] == "task_timeout" for e in result.events)
    assert any(e["event_type"] == "task_cancelled" for e in result.events)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/triada/test_long_running.py -q
```

Expected: FAIL because services are not implemented.

- [ ] **Step 3: Implement heartbeat service**

Create `app/services/heartbeat.py` with `HeartbeatService` that emits `agent_heartbeat` payloads containing trace, agent, current stage, last completed action, elapsed seconds, and created timestamp.

- [ ] **Step 4: Implement supervisor and fake clock**

Create `app/services/execution_supervisor.py` with:

- `FakeClock`
- `LongTaskSimulationResult`
- `LongTaskSimulator.run_virtual(...)`
- timeout/cancellation event generation

- [ ] **Step 5: Implement task service shell**

Create `app/services/task_service.py` with:

- `create_task`
- `get_task`
- `cancel_task`
- `approve_task`
- `resume_task`
- `run_task_once`

Use repository/emitter contracts. Keep execution synchronous-in-process for MVP.

- [ ] **Step 6: Run long-running tests**

Run:

```bash
pytest tests/triada/test_long_running.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add app/services tests/triada/test_long_running.py
git commit -m "feat: add long-running task supervision"
```

---

## Task 9: FastAPI Routes And SSE Restore

**Files:**
- Create: `app/api/routes.py`
- Create/Modify: `app/main.py`
- Create: `app/schemas/tasks.py`
- Test: `tests/triada/test_api_sse.py`

- [ ] **Step 1: Write failing API tests**

Create `tests/triada/test_api_sse.py`:

```python
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.mark.asyncio
async def test_create_task_and_list_events():
    app = create_app(testing=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/v1/tasks",
            json={
                "goal": "Inspect repository",
                "allowed_tools": ["git"],
                "acceptance_criteria": ["Return git status"],
            },
        )
        assert created.status_code == 201
        task_id = created.json()["task_id"]

        events = await client.get(f"/v1/tasks/{task_id}/events")
        assert events.status_code == 200
        assert events.json()["events"]


@pytest.mark.asyncio
async def test_sse_last_event_id_restores_stream():
    app = create_app(testing=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/v1/tasks", json={"goal": "Demo", "allowed_tools": ["shell"]})
        task_id = created.json()["task_id"]
        events = (await client.get(f"/v1/tasks/{task_id}/events")).json()["events"]
        first_id = events[0]["id"]
        stream = await client.get(
            f"/v1/tasks/{task_id}/stream",
            headers={"Last-Event-ID": first_id},
        )
        assert stream.status_code == 200
        assert "text/event-stream" in stream.headers["content-type"]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/triada/test_api_sse.py -q
```

Expected: FAIL because API routes are missing.

- [ ] **Step 3: Implement task schemas**

Create `app/schemas/tasks.py` with:

- `CreateTaskRequest`
- `TaskResponse`
- `TaskEventsResponse`
- `ApprovalRequest`
- `TaskActionResponse`

- [ ] **Step 4: Implement FastAPI app**

Create `app/main.py` with `create_app(testing: bool = False) -> FastAPI`. Include routes and app state with test database/session factories.

- [ ] **Step 5: Implement routes**

Create `app/api/routes.py` with all MVP endpoints from the spec. SSE endpoint must format persisted events and honor `Last-Event-ID`.

- [ ] **Step 6: Run API tests**

Run:

```bash
pytest tests/triada/test_api_sse.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add app/api app/main.py app/schemas/tasks.py tests/triada/test_api_sse.py
git commit -m "feat: add task api and sse stream"
```

---

## Task 10: CLI And Demo Commands

**Files:**
- Create/Modify: `app/cli.py`
- Test: `tests/triada/test_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Create `tests/triada/test_cli.py`:

```python
from app.cli import main


def test_cli_demo_runs(capsys):
    exit_code = main(["demo"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "TRIADA demo" in captured.out
    assert "audit verdict" in captured.out


def test_cli_simulate_long_task_runs(capsys):
    exit_code = main(["simulate-long-task"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "agent_heartbeat" in captured.out
    assert "thinking_summary_delta" in captured.out


def test_cli_test_provider_uses_fake_by_default(capsys):
    exit_code = main(["test-provider"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "fake-devops-model" in captured.out
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/triada/test_cli.py -q
```

Expected: FAIL because CLI commands are not implemented.

- [ ] **Step 3: Implement CLI**

Create `app/cli.py` with `argparse` commands:

- `demo`
- `run-task task.json`
- `verify-trace TRACE_ID`
- `list-events TRACE_ID`
- `simulate-long-task`
- `test-provider`

Return integer exit codes from `main(argv: list[str] | None = None)`.

- [ ] **Step 4: Run CLI tests**

Run:

```bash
pytest tests/triada/test_cli.py -q
```

Expected: PASS.

- [ ] **Step 5: Run manual CLI commands**

Run:

```bash
python -m app.cli demo
python -m app.cli simulate-long-task
python -m app.cli test-provider
```

Expected: each command exits 0 and prints demo/provider/simulation output.

- [ ] **Step 6: Commit**

Run:

```bash
git add app/cli.py tests/triada/test_cli.py
git commit -m "feat: add triada cli demos"
```

---

## Task 11: Documentation And Docker Compose

**Files:**
- Create/Modify: `README.md`
- Create: `ARCHITECTURE.md`
- Create: `SECURITY.md`
- Create: `AUDIT_MODEL.md`
- Create: `EVENT_SCHEMA.md`
- Create: `LONG_RUNNING_TASKS.md`
- Create: `DEVOPS_TOOLS.md`
- Create: `AGENTS.md`
- Create: `.env.example`
- Create: `docker-compose.yml`
- Test: `tests/triada/test_docs.py`

- [ ] **Step 1: Write docs presence tests**

Create `tests/triada/test_docs.py`:

```python
from pathlib import Path


def test_required_docs_exist_and_contain_core_terms():
    required = [
        "README.md",
        "ARCHITECTURE.md",
        "SECURITY.md",
        "AUDIT_MODEL.md",
        "EVENT_SCHEMA.md",
        "LONG_RUNNING_TASKS.md",
        "DEVOPS_TOOLS.md",
        "AGENTS.md",
        ".env.example",
        "docker-compose.yml",
    ]
    for path in required:
        assert Path(path).exists(), path

    architecture = Path("ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "flowchart TD" in architecture
    assert "Orchestrator" in architecture
    assert "Auditor" in architecture
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/triada/test_docs.py -q
```

Expected: FAIL until required docs exist.

- [ ] **Step 3: Write docs**

Create docs from the approved design:

- `README.md`: quickstart, install, API, CLI, validation commands.
- `ARCHITECTURE.md`: triad diagram and control boundaries.
- `SECURITY.md`: redaction, approval, risk policy, no CoT capture.
- `AUDIT_MODEL.md`: append-only events, hash-chain, auditor evidence priority.
- `EVENT_SCHEMA.md`: event and delta schema examples.
- `LONG_RUNNING_TASKS.md`: lease, heartbeat, checkpoint, timeout, fake clock.
- `DEVOPS_TOOLS.md`: adapter contracts and safe command matrix.
- `AGENTS.md`: project instructions for future agents.
- `.env.example`: required env vars from spec.
- `docker-compose.yml`: FastAPI service and PostgreSQL service.

- [ ] **Step 4: Run docs test**

Run:

```bash
pytest tests/triada/test_docs.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add README.md ARCHITECTURE.md SECURITY.md AUDIT_MODEL.md EVENT_SCHEMA.md LONG_RUNNING_TASKS.md DEVOPS_TOOLS.md AGENTS.md .env.example docker-compose.yml tests/triada/test_docs.py
git commit -m "docs: add triada architecture and operations docs"
```

---

## Task 12: Final Validation And Push

**Files:**
- Modify as needed based on validation failures.

- [ ] **Step 1: Compile application**

Run:

```bash
python -m compileall app
```

Expected: exits 0.

- [ ] **Step 2: Run all tests**

Run:

```bash
pytest -q
```

Expected: all tests pass, including existing FixMost tests and new `tests/triada` tests.

- [ ] **Step 3: Run Alembic migration**

Run:

```bash
DATABASE_URL=sqlite+aiosqlite:///./triada-validation.db alembic upgrade head
```

Expected: migration applies cleanly.

- [ ] **Step 4: Run CLI demos**

Run:

```bash
python -m app.cli demo
python -m app.cli simulate-long-task
```

Expected: both commands exit 0. Demo prints audit verdict. Long task prints heartbeat, progress, thinking deltas, and final status.

- [ ] **Step 5: Start API manually**

Run:

```bash
uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

Expected: app starts. In another shell, `POST /v1/tasks` and `GET /v1/tasks/{task_id}/stream` respond.

- [ ] **Step 6: Commit validation fixes**

If validation required fixes, commit them:

```bash
git add app tests docs README.md ARCHITECTURE.md SECURITY.md AUDIT_MODEL.md EVENT_SCHEMA.md LONG_RUNNING_TASKS.md DEVOPS_TOOLS.md AGENTS.md .env.example docker-compose.yml pyproject.toml alembic.ini alembic
git commit -m "test: validate triada mvp"
```

Skip this commit if there are no changes.

- [ ] **Step 7: Push to GitHub**

Run:

```bash
git remote add origin git@github.com:Personal1ty/TRIADA.git
git branch -M main
git push -u origin main
```

Expected: push succeeds using the configured SSH key.

---

## Plan Self-Review

- Spec coverage: the plan covers project packaging, schemas, redaction, persistence, hash-chain, event emitter, provider routing, tools, agents, auditor, long-running simulation, API/SSE, CLI, docs, validation, and push.
- Scope: this is still one MVP framework plan. Deep write-enabled DevOps automation remains out of MVP and is intentionally constrained by risk policy.
- Execution order: each task builds on previous contracts and has focused tests before implementation.
- Local model delegation: implementation supports FakeLLM for tests and OpenAI-compatible runtime provider for local endpoints and FixMost/corp-coder profile.
- GitHub target: final push target is `git@github.com:Personal1ty/TRIADA.git`.
