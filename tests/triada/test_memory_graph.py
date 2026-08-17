from types import SimpleNamespace

import pytest

from app.audit.projection import memory_graph_from_events
from app.schemas.tasks import MemoryRelationRequest


def test_memory_graph_projects_notes_relations_and_conflicts():
    events = [
        SimpleNamespace(
            event_type="memory_note_added",
            task_id="task-1",
            payload={"memory_id": "m-1", "kind": "decision", "title": "Use Postgres", "content": "Durable state"},
        ),
        SimpleNamespace(
            event_type="memory_note_added",
            task_id="task-1",
            payload={"memory_id": "m-2", "kind": "constraint", "title": "No SQLite", "content": "Production uses Postgres"},
        ),
        SimpleNamespace(
            event_type="memory_relation_added",
            task_id="task-1",
            payload={"relation_id": "r-1", "source_memory_id": "m-1", "target_memory_id": "m-2", "relation": "contradicts", "reason": "Conflict"},
        ),
    ]

    graph = memory_graph_from_events(events)

    assert graph["summary"] == {"node_count": 2, "edge_count": 1, "conflict_count": 1}
    assert graph["edges"][0]["relation"] == "contradicts"
    assert graph["conflicts"][0]["source_memory_id"] == "m-1"


def test_memory_relation_request_rejects_unknown_relation():
    with pytest.raises(ValueError):
        MemoryRelationRequest(
            source_memory_id="m-1",
            target_memory_id="m-2",
            relation="mentions",
        )


def test_memory_graph_keeps_cross_task_nodes_and_edges():
    events = [
        SimpleNamespace(
            event_type="memory_note_added",
            task_id="task-a",
            payload={"memory_id": "m-a", "kind": "decision", "title": "A", "content": "First"},
        ),
        SimpleNamespace(
            event_type="memory_note_added",
            task_id="task-b",
            payload={"memory_id": "m-b", "kind": "observation", "title": "B", "content": "Second"},
        ),
        SimpleNamespace(
            event_type="memory_relation_added",
            task_id="task-a",
            payload={"relation_id": "r-ab", "source_memory_id": "m-a", "target_memory_id": "m-b", "relation": "supports"},
        ),
    ]

    graph = memory_graph_from_events(events)

    assert {node["task_id"] for node in graph["nodes"]} == {"task-a", "task-b"}
    assert graph["edges"][0]["relation"] == "supports"


def test_memory_graph_detects_conflicting_parameter_values():
    events = [
        SimpleNamespace(
            event_type="memory_note_added",
            task_id="task-a",
            payload={
                "memory_id": "m-a",
                "kind": "decision",
                "title": "Timeout A",
                "content": "Use 30 seconds",
                "parameter_key": "timeout_seconds",
                "parameter_value": "30",
            },
        ),
        SimpleNamespace(
            event_type="memory_note_added",
            task_id="task-b",
            payload={
                "memory_id": "m-b",
                "kind": "decision",
                "title": "Timeout B",
                "content": "Use 60 seconds",
                "parameter_key": "timeout_seconds",
                "parameter_value": "60",
            },
        ),
    ]

    graph = memory_graph_from_events(events)

    assert graph["summary"]["conflict_count"] == 1
    assert graph["conflicts"][0]["relation"] == "parameter_conflict"
