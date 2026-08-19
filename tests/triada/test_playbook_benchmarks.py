from types import SimpleNamespace
from uuid import uuid4

from app.audit.projection import playbook_benchmarks_from_events


def test_playbook_benchmarks_compare_quality_cost_and_tokens_per_quality():
    def event(payload, sequence):
        return SimpleNamespace(id=uuid4(), task_id=uuid4(), event_type="playbook_run_recorded", payload=payload, sequence=sequence)

    result = playbook_benchmarks_from_events([
        event({"name": "research", "version": "1.0", "status": "completed", "quality_score": 0.5, "tokens": 100, "estimated_cost": 0.02}, 1),
        event({"name": "research", "version": "1.0", "status": "completed", "quality_score": 1.0, "tokens": 100, "estimated_cost": 0.04}, 2),
    ])

    assert result["benchmarks"][0]["run_count"] == 2
    assert result["benchmarks"][0]["average_quality"] == 0.75
    assert result["benchmarks"][0]["tokens_per_quality"] == 266.6667
