from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.audit.projection import playbook_runs_from_events
from app.schemas.tasks import PlaybookRunRequest


def _event(payload, sequence=1):
    return SimpleNamespace(id=uuid4(), task_id=uuid4(), event_type="playbook_run_recorded", payload=payload, sequence=sequence)


def test_playbook_projection_compares_runs_by_quality_and_cost():
    result = playbook_runs_from_events([
        _event({"run_id": "run-1", "name": "research-v1", "version": "1.0", "status": "completed", "quality_score": 0.7, "tokens": 200, "estimated_cost": 0.04}),
        _event({"run_id": "run-2", "name": "research-v1", "version": "1.0", "status": "completed", "quality_score": 0.9, "tokens": 150, "estimated_cost": 0.03}, 2),
    ])

    assert result["summary"] == {"run_count": 2, "completed_count": 2, "best_quality_score": 0.9, "total_tokens": 350, "total_estimated_cost": 0.07}
    assert result["runs"][0]["run_id"] == "run-2"


def test_playbook_request_rejects_invalid_score_and_secret_notes():
    with pytest.raises(ValueError):
        PlaybookRunRequest(name="research-v1", version="1.0", quality_score=1.1)
    with pytest.raises(ValueError):
        PlaybookRunRequest(name="research-v1", version="1.0", note="token=secret")
