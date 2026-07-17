import asyncio
from uuid import uuid4

import pytest

from app.audit.repository import AuditEventRepository
from app.persistence.session import create_session_factory


async def _append_event(repo, trace_id, task_id, index):
    return await repo.append_event(
        event_type="worker_progress",
        trace_id=trace_id,
        task_id=task_id,
        agent_id="worker",
        payload={"index": index},
    )


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


@pytest.mark.asyncio
async def test_concurrent_first_append_creates_tables_once_and_preserves_hash_chain(tmp_path):
    session_factory = create_session_factory(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    repo = AuditEventRepository(session_factory)
    trace_id = uuid4()
    task_id = uuid4()

    events = await asyncio.gather(
        *(_append_event(repo, trace_id, task_id, index) for index in range(20))
    )

    assert len(events) == 20
    assert await repo.verify_trace(trace_id) is True


@pytest.mark.asyncio
async def test_concurrent_append_after_tables_exist_serializes_sequences_and_hashes(tmp_path):
    session_factory = create_session_factory(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    repo = AuditEventRepository(session_factory)
    trace_id = uuid4()
    task_id = uuid4()
    await repo.list_events(trace_id)

    await asyncio.gather(*(_append_event(repo, trace_id, task_id, index) for index in range(20)))

    events = await repo.list_events(trace_id)
    assert [event.sequence for event in events] == list(range(1, 21))
    assert sum(1 for event in events if event.previous_hash == "") == 1
    assert await repo.verify_trace(trace_id) is True
