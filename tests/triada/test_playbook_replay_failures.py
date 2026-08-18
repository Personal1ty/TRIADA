from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.audit.projection import failure_catalog_from_events, playbook_replays_from_events
from app.schemas.tasks import FailurePatternRequest, PlaybookReplayRequest


def _event(event_type, payload, sequence=1):
    return SimpleNamespace(id=uuid4(), task_id=uuid4(), event_type=event_type, payload=payload, sequence=sequence)


def test_playbook_replay_projection_keeps_source_and_status():
    result = playbook_replays_from_events([_event("playbook_replay_requested", {"replay_id": "r-1", "source_run_id": "run-1", "status": "requested"})])

    assert result["summary"] == {"replay_count": 1, "completed_count": 0}
    assert result["replays"][0]["source_run_id"] == "run-1"


def test_failure_catalog_deduplicates_latest_pattern():
    result = failure_catalog_from_events([
        _event("failure_pattern_recorded", {"failure_id": "f-1", "category": "timeout", "symptom": "Slow tool", "cause": "No budget", "mitigation": "Set timeout"}),
        _event("failure_pattern_recorded", {"failure_id": "f-2", "category": "timeout", "symptom": "Slow tool", "cause": "No budget", "mitigation": "Set timeout and retry"}, 2),
    ])

    assert result["summary"]["pattern_count"] == 1
    assert result["patterns"][0]["mitigation"] == "Set timeout and retry"


def test_replay_and_failure_requests_reject_secret_text():
    with pytest.raises(ValueError):
        PlaybookReplayRequest(source_run_id="run-1", note="token=secret")
    with pytest.raises(ValueError):
        FailurePatternRequest(category="timeout", symptom="x", cause="y", mitigation="token=secret")
