from types import SimpleNamespace
from uuid import uuid4

from app.audit.projection import resource_economics_from_events


def _event(event_type, payload, sequence=1):
    return SimpleNamespace(id=uuid4(), task_id=uuid4(), event_type=event_type, payload=payload, sequence=sequence)


def test_resource_economics_projects_utilization_and_sufficiency():
    result = resource_economics_from_events([
        _event("resource_allocation_decided", {"budget": {"max_tokens": 1000, "max_duration_ms": 2000, "max_parallel_branches": 4}}),
        _event("resource_usage_recorded", {"agent_role": "worker", "tokens": 600, "duration_ms": 1000, "branches": 2}, 2),
    ])

    assert result["utilization"] == {"tokens": 0.6, "duration_ms": 0.5, "parallel_branches": 0.5}
    assert result["signals"] == {"sufficient": True, "waste": False}
