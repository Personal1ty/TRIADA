from __future__ import annotations

from uuid import uuid4

import pytest

from app.agents.orchestrator import Orchestrator
from app.config import get_settings
from app.llm.openai_compatible import OpenAICompatibleProvider
from app.services.execution_engine import ExecutionEngine
from app.services.task_service import TaskRecord, TaskService


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class MemoryEmitter:
    def __init__(self) -> None:
        self.events = []

    async def emit(self, **kwargs):
        self.events.append(kwargs)


class UnavailableLLM:
    async def complete_json(self, prompt: str, *, schema_name: str):
        raise RuntimeError("connection refused")


def make_task(*, goal: str, allowed_tools: list[str] | None = None) -> TaskRecord:
    return TaskRecord(
        id=uuid4(),
        trace_id=uuid4(),
        goal=goal,
        allowed_tools=allowed_tools or ["shell"],
        acceptance_criteria=["task handled"],
    )


def test_execution_engine_uses_openai_compatible_provider_from_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("LLM_MODEL", "corp-coder")
    get_settings.cache_clear()

    engine = ExecutionEngine(emitter=MemoryEmitter(), workspace=tmp_path)

    assert isinstance(engine._orchestrator.llm, OpenAICompatibleProvider)
    assert engine._orchestrator.llm.base_url == "http://127.0.0.1:11434/v1"
    assert engine._orchestrator.llm.model == "corp-coder"


@pytest.mark.asyncio
async def test_execution_engine_blocks_and_emits_llm_unavailable_when_provider_fails(tmp_path):
    emitter = MemoryEmitter()
    engine = ExecutionEngine(
        emitter=emitter,
        workspace=tmp_path,
        orchestrator=Orchestrator(UnavailableLLM()),
    )
    task = make_task(goal="Inspect repository", allowed_tools=["git"])

    status = await engine.run_once(task)

    assert status == "blocked"
    event_types = [event["event_type"] for event in emitter.events]
    assert "llm_unavailable" in event_types
    assert "planning_completed" not in event_types
    unavailable = next(event for event in emitter.events if event["event_type"] == "llm_unavailable")
    assert unavailable["payload"]["status"] == "blocked"
    assert unavailable["payload"]["provider"] == "UnavailableLLM"


@pytest.mark.asyncio
async def test_write_task_waits_for_approval_before_worker_execution(tmp_path):
    emitter = MemoryEmitter()
    service = TaskService(
        emitter=emitter,
        execution_engine=ExecutionEngine(emitter=emitter, workspace=tmp_path),
    )
    task = await service.create_task(
        goal="write a deployment marker",
        allowed_tools=["shell"],
        acceptance_criteria=["change approved"],
    )

    waiting = await service.run_task_once(task.id)

    assert waiting.status == "waiting_approval"
    event_types = [event["event_type"] for event in emitter.events]
    assert "approval_required" in event_types
    assert "worker_step_started" not in event_types
    assert event_types[-1] == "task_waiting_approval"


@pytest.mark.asyncio
async def test_approved_write_task_can_continue_to_worker(tmp_path):
    emitter = MemoryEmitter()
    service = TaskService(
        emitter=emitter,
        execution_engine=ExecutionEngine(emitter=emitter, workspace=tmp_path),
    )
    task = await service.create_task(
        goal="write a deployment marker",
        allowed_tools=["shell"],
        acceptance_criteria=["change approved"],
    )
    await service.run_task_once(task.id)
    await service.approve_task(task.id, approved_by="operator")

    completed = await service.run_task_once(task.id)

    assert completed.status == "completed"
    event_types = [event["event_type"] for event in emitter.events]
    assert "task_approved" in event_types
    assert "worker_step_completed" in event_types
