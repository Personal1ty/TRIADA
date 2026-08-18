from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.audit.projection import resource_usage_from_events
from app.schemas.tasks import ResourceUsageRecordRequest


def _event(payload, sequence=1):
    return SimpleNamespace(id=uuid4(), task_id=uuid4(), event_type="resource_usage_recorded", payload=payload, sequence=sequence)


def test_resource_usage_projection_aggregates_tokens_time_cost_and_branches():
    projection = resource_usage_from_events([
        _event({"usage_id": "u-1", "agent_role": "worker", "tokens": 120, "duration_ms": 500, "estimated_cost": 0.02, "branches": 2}),
        _event({"usage_id": "u-2", "agent_role": "auditor", "tokens": 80, "duration_ms": 300, "estimated_cost": 0.01, "branches": 1}, 2),
    ])

    assert projection["summary"] == {"record_count": 2, "tokens": 200, "duration_ms": 800, "estimated_cost": 0.03, "branches": 3}
    assert projection["by_role"]["worker"]["tokens"] == 120


def test_resource_usage_request_rejects_negative_values_and_secrets():
    with pytest.raises(ValueError):
        ResourceUsageRecordRequest(agent_role="worker", tokens=-1)
    with pytest.raises(ValueError):
        ResourceUsageRecordRequest(agent_role="worker", note="token=secret")
