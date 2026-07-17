import pytest

from app.services.heartbeat import HeartbeatService
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
