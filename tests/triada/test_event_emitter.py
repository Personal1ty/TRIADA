import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.audit.emitter import AuditEmitter
from app.audit.projection import event_to_sse, events_to_public_response, thinking_deltas_from_events
from app.audit.repository import AuditEventRepository
from app.events.bus import InMemoryEventBus
from app.persistence.session import create_session_factory


async def _dispose_session_factory(session_factory):
    bind = session_factory.kw.get("bind")
    if bind is not None:
        await bind.dispose()


@pytest.mark.asyncio
async def test_emitter_persists_before_publish(tmp_path):
    session_factory = create_session_factory(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    repo = AuditEventRepository(session_factory)
    bus = InMemoryEventBus()
    emitter = AuditEmitter(repo, bus)
    trace_id = uuid4()
    task_id = uuid4()

    try:
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
    finally:
        await _dispose_session_factory(session_factory)


@pytest.mark.asyncio
async def test_emitter_redacts_payload_before_persistence(tmp_path):
    session_factory = create_session_factory(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    repo = AuditEventRepository(session_factory)
    emitter = AuditEmitter(repo, InMemoryEventBus())

    try:
        event = await emitter.emit(
            event_type="tool_execution_completed",
            trace_id=uuid4(),
            task_id=uuid4(),
            agent_id="worker-1",
            payload={"stdout": "Authorization: Bearer sk-secret"},
        )

        assert "sk-secret" not in str(event.payload)
        assert "[REDACTED]" in str(event.payload)
    finally:
        await _dispose_session_factory(session_factory)


@pytest.mark.asyncio
async def test_emitter_does_not_publish_when_append_fails():
    class FailingRepo:
        async def append_event(self, **kwargs):
            raise ValueError("append failed")

    bus = InMemoryEventBus()
    emitter = AuditEmitter(FailingRepo(), bus)

    with pytest.raises(ValueError, match="append failed"):
        await emitter.emit(
            event_type="task_created",
            trace_id=uuid4(),
            task_id=uuid4(),
            agent_id="orchestrator",
            payload={},
        )

    assert await bus.drain() == []


@pytest.mark.asyncio
async def test_bus_subscription_receives_only_matching_trace(tmp_path):
    session_factory = create_session_factory(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    repo = AuditEventRepository(session_factory)
    bus = InMemoryEventBus()
    emitter = AuditEmitter(repo, bus)
    trace_id = uuid4()

    try:
        subscription = await bus.subscribe(trace_id)
        await emitter.emit(
            event_type="task_created",
            trace_id=uuid4(),
            task_id=uuid4(),
            agent_id="orchestrator",
            payload={"message": "ignored"},
        )
        expected = await emitter.emit(
            event_type="task_created",
            trace_id=trace_id,
            task_id=uuid4(),
            agent_id="orchestrator",
            payload={"message": "delivered"},
        )

        received = await subscription.__anext__()
        await subscription.aclose()

        assert received.id == expected.id
        assert await bus.listener_count(trace_id) == 0
    finally:
        await _dispose_session_factory(session_factory)


@pytest.mark.asyncio
async def test_bus_publish_returns_promptly_and_removes_full_slow_listener():
    bus = InMemoryEventBus(listener_queue_size=1)
    trace_id = uuid4()
    slow_subscription = await bus.subscribe(trace_id)
    first_event = SimpleNamespace(id=str(uuid4()), trace_id=str(trace_id))
    second_event = SimpleNamespace(id=str(uuid4()), trace_id=str(trace_id))

    await bus.publish(first_event)

    await asyncio.wait_for(bus.publish(second_event), timeout=0.1)

    assert await bus.listener_count(trace_id) == 0
    await slow_subscription.aclose()


@pytest.mark.asyncio
async def test_bus_publish_continues_to_healthy_listener_when_slow_listener_overflows():
    bus = InMemoryEventBus(listener_queue_size=1)
    trace_id = uuid4()
    slow_subscription = await bus.subscribe(trace_id)
    first_event = SimpleNamespace(id=str(uuid4()), trace_id=str(trace_id))
    second_event = SimpleNamespace(id=str(uuid4()), trace_id=str(trace_id))

    await bus.publish(first_event)
    healthy_subscription = await bus.subscribe(trace_id)

    await asyncio.wait_for(bus.publish(second_event), timeout=0.1)

    received = await asyncio.wait_for(healthy_subscription.__anext__(), timeout=0.1)
    assert received.id == second_event.id
    assert await bus.listener_count(trace_id) == 1
    await slow_subscription.aclose()
    await healthy_subscription.aclose()


def test_projection_serializes_nested_uuid_datetime_payload_and_span_fields():
    event = SimpleNamespace(
        id=uuid4(),
        event_type="tool_execution_completed",
        trace_id=uuid4(),
        task_id=uuid4(),
        agent_id="worker-1",
        span_id=uuid4(),
        parent_span_id=uuid4(),
        sequence=1,
        payload={
            "artifact_id": uuid4(),
            "timestamps": [datetime(2026, 7, 17, 12, 0, tzinfo=UTC)],
            "nested": {"when": datetime(2026, 7, 17, 13, 0, tzinfo=UTC)},
        },
        created_at=datetime(2026, 7, 17, 14, 0, tzinfo=UTC),
    )

    sse = event_to_sse(event)
    public_response = events_to_public_response([event])

    json.dumps(public_response)
    sse_data = json.loads(sse["data"])
    assert sse_data["span_id"] == str(event.span_id)
    assert sse_data["parent_span_id"] == str(event.parent_span_id)
    assert sse_data["payload"]["artifact_id"] == str(event.payload["artifact_id"])
    assert sse_data["payload"]["timestamps"][0] == "2026-07-17T12:00:00+00:00"


def test_projection_redacts_raw_model_reasoning_from_public_events():
    event = SimpleNamespace(
        id=uuid4(),
        event_type="model_reasoning_content_captured",
        trace_id=uuid4(),
        task_id=uuid4(),
        agent_id="worker-1",
        span_id=None,
        parent_span_id=None,
        sequence=1,
        payload={
            "schema_version": "1.0",
            "agent_role": "worker",
            "raw_reasoning_content": "raw private model reasoning",
        },
        created_at=datetime(2026, 7, 17, 14, 0, tzinfo=UTC),
    )

    public_response = events_to_public_response([event])

    assert "raw_reasoning_content" not in public_response[0]["payload"]
    assert "raw private model reasoning" not in json.dumps(public_response)


@pytest.mark.asyncio
async def test_projection_exposes_public_event_and_thinking_delta(tmp_path):
    session_factory = create_session_factory(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    repo = AuditEventRepository(session_factory)
    emitter = AuditEmitter(repo, InMemoryEventBus())
    trace_id = uuid4()
    task_id = uuid4()

    try:
        event = await emitter.emit(
            event_type="thinking_summary_delta",
            trace_id=trace_id,
            task_id=task_id,
            agent_id="worker-1",
            payload={
                "span_id": str(uuid4()),
                "agent_role": "worker",
                "source": "runtime",
                "stage": "implementation",
                "action": "write tests",
                "summary": "Added the failing event emitter tests.",
            },
        )

        sse = event_to_sse(event)
        assert sse["id"] == event.id
        assert sse["event"] == event.event_type
        assert json.loads(sse["data"])["id"] == event.id

        public_events = events_to_public_response([event])
        assert public_events[0]["id"] == event.id
        assert public_events[0]["payload"]["summary"] == "Added the failing event emitter tests."

        deltas = thinking_deltas_from_events([event])
        assert deltas[0]["event_id"] == event.id
        assert deltas[0]["sequence"] == event.sequence
        assert deltas[0]["task_id"] == event.task_id
    finally:
        await _dispose_session_factory(session_factory)
