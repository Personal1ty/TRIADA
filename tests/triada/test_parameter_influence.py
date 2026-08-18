from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.audit.projection import parameter_influence_from_events
from app.schemas.tasks import ParameterInfluenceRequest


def _event(payload, sequence=1):
    return SimpleNamespace(
        id=uuid4(), task_id=uuid4(), event_type="parameter_influence_recorded",
        payload=payload, sequence=sequence,
    )


def test_parameter_influence_projection_orders_edges_and_summarizes_strength():
    projection = parameter_influence_from_events([
        _event({"influence_id": "i-1", "source_parameter": "parallelism", "target_parameter": "latency", "weight": -0.8, "reason": "More branches increase contention"}),
        _event({"influence_id": "i-2", "source_parameter": "retries", "target_parameter": "quality", "weight": 0.4, "reason": "Retries recover transient failures"}, 2),
    ])

    assert projection["summary"] == {"influence_count": 2, "strong_count": 1, "average_absolute_weight": 0.6}
    assert projection["influences"][0]["weight"] == -0.8


def test_parameter_influence_request_rejects_out_of_range_weight_and_secrets():
    with pytest.raises(ValueError):
        ParameterInfluenceRequest(source_parameter="a", target_parameter="b", weight=1.1)
    with pytest.raises(ValueError):
        ParameterInfluenceRequest(source_parameter="a", target_parameter="b", weight=0.2, reason="token=secret")
