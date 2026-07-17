import json
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
        subscription = bus.subscribe(trace_id)
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
        assert bus.listener_count(trace_id) == 0
    finally:
        await _dispose_session_factory(session_factory)


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
