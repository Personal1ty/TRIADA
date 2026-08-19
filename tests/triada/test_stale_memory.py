from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from app.audit.projection import memory_graph_from_events


def test_memory_graph_marks_expired_notes_as_stale():
    expired = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    event = SimpleNamespace(
        id=uuid4(), task_id=uuid4(), event_type="memory_note_added", sequence=1,
        payload={"memory_id": "m-1", "kind": "decision", "title": "Old", "content": "Old assumption", "valid_until": expired},
    )

    graph = memory_graph_from_events([event])

    assert graph["summary"]["stale_count"] == 1
    assert graph["nodes"][0]["stale"] is True
