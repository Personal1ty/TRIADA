import json
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.audit.projection import thinking_deltas_from_events
from app.events.models import ThinkingSummaryDelta
from app.services.heartbeat import HeartbeatService
from app.services.execution_supervisor import FakeClock, LongTaskSimulator
from app.services.task_service import TaskService


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


@pytest.mark.asyncio
async def test_heartbeats_are_emitted_at_heartbeat_interval():
    clock = FakeClock(start=0)
    simulator = LongTaskSimulator(clock=clock, heartbeat_seconds=60, checkpoint_seconds=300)

    result = await simulator.run_virtual(duration_seconds=4 * 60, timeout_seconds=3 * 60 * 60)

    heartbeat_times = [
        e["payload"]["elapsed_seconds"]
        for e in result.events
        if e["event_type"] == "agent_heartbeat"
    ]
    assert heartbeat_times == [60, 120, 180, 240]


@pytest.mark.asyncio
async def test_thinking_checkpoints_are_no_more_than_checkpoint_interval_apart():
    clock = FakeClock(start=0)
    simulator = LongTaskSimulator(clock=clock, heartbeat_seconds=60, checkpoint_seconds=300)

    result = await simulator.run_virtual(duration_seconds=16 * 60, timeout_seconds=3 * 60 * 60)

    checkpoint_times = [
        e["payload"]["elapsed_seconds"]
        for e in result.events
        if e["event_type"] == "thinking_summary_delta"
    ]
    assert checkpoint_times == [300, 600, 900]
    assert all(
        current - previous <= 300
        for previous, current in zip(checkpoint_times, checkpoint_times[1:])
    )


@pytest.mark.asyncio
async def test_timeout_occurs_at_timeout_seconds_not_duration_seconds():
    clock = FakeClock(start=0)
    simulator = LongTaskSimulator(clock=clock, heartbeat_seconds=60, checkpoint_seconds=300)

    result = await simulator.run_virtual(duration_seconds=4 * 60 * 60, timeout_seconds=3 * 60 * 60)

    timeout_events = [e for e in result.events if e["event_type"] == "task_timeout"]
    assert [e["payload"]["elapsed_seconds"] for e in timeout_events] == [3 * 60 * 60]
    assert result.elapsed_seconds == 3 * 60 * 60


@pytest.mark.asyncio
async def test_task_completes_when_duration_equals_timeout():
    clock = FakeClock(start=0)
    simulator = LongTaskSimulator(clock=clock, heartbeat_seconds=60, checkpoint_seconds=300)

    result = await simulator.run_virtual(duration_seconds=3 * 60 * 60, timeout_seconds=3 * 60 * 60)

    assert result.status == "completed"
    assert not any(e["event_type"] == "task_timeout" for e in result.events)
    assert any(e["event_type"] == "task_completed" for e in result.events)


@pytest.mark.asyncio
async def test_heartbeat_payload_includes_supervision_fields():
    clock = FakeClock(start=0)
    service = HeartbeatService(clock=clock)

    event = await service.emit(
        trace_id="trace-1",
        task_id="task-1",
        agent_id="worker-1",
        current_stage="implementation",
        last_completed_action="wrote tests",
        elapsed_seconds=60,
    )

    assert event["event_type"] == "agent_heartbeat"
    assert event["trace_id"] == "trace-1"
    assert event["agent_id"] == "worker-1"
    assert event["payload"] == {
        "trace_id": "trace-1",
        "agent_id": "worker-1",
        "current_stage": "implementation",
        "last_completed_action": "wrote tests",
        "elapsed_seconds": 60,
        "created_at": "1970-01-01T00:01:00+00:00",
    }


@pytest.mark.asyncio
async def test_long_task_events_are_json_safe_and_projectable():
    clock = FakeClock(start=0)
    simulator = LongTaskSimulator(clock=clock, heartbeat_seconds=60, checkpoint_seconds=300)

    result = await simulator.run_virtual(duration_seconds=6 * 60, timeout_seconds=3 * 60 * 60)

    json.dumps(result.events)
    projected = thinking_deltas_from_events(
        [
            SimpleNamespace(
                id=uuid4(),
                event_type=event["event_type"],
                trace_id=event["trace_id"],
                task_id=event["task_id"],
                agent_id=event["agent_id"],
                span_id=None,
                parent_span_id=None,
                sequence=index + 1,
                payload=event["payload"],
                created_at=datetime.fromisoformat(event["created_at"]),
            )
            for index, event in enumerate(result.events)
        ]
    )

    assert projected
    ThinkingSummaryDelta(**projected[0])


@pytest.mark.asyncio
async def test_task_service_copies_mutable_task_inputs():
    service = TaskService()
    constraints = {"paths": ["app"]}
    allowed_tools = ["git"]
    acceptance_criteria = ["tests pass"]
    metadata = {"labels": ["mvp"]}

    task = await service.create_task(
        goal="ship",
        constraints=constraints,
        allowed_tools=allowed_tools,
        acceptance_criteria=acceptance_criteria,
        metadata=metadata,
    )
    constraints["paths"].append("mutated")
    allowed_tools.append("shell")
    acceptance_criteria.append("mutated")
    metadata["labels"].append("mutated")

    assert task.constraints == {"paths": ["app"]}
    assert task.allowed_tools == ["git"]
    assert task.acceptance_criteria == ["tests pass"]
    assert task.metadata == {"labels": ["mvp"]}


@pytest.mark.asyncio
async def test_task_service_does_not_mutate_in_memory_state_when_emit_fails():
    class FailingEmitter:
        async def emit(self, **kwargs):
            raise RuntimeError("emit failed")

    service = TaskService()
    task = await service.create_task(goal="ship")
    service._emitter = FailingEmitter()

    with pytest.raises(RuntimeError, match="emit failed"):
        await service.cancel_task(task.id)

    stored = await service.get_task(task.id)
    assert stored is not None
    assert stored.status == "created"
