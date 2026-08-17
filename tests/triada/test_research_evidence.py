from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.audit.projection import research_evidence_from_events
from app.schemas.tasks import ResearchEvidenceRequest


def _event(event_type: str, payload: dict, sequence: int = 1):
    return SimpleNamespace(
        id=uuid4(),
        task_id=uuid4(),
        event_type=event_type,
        payload=payload,
        sequence=sequence,
    )


def test_evidence_projection_maps_hypotheses_and_reports_open_questions():
    events = [
        _event(
            "research_plan_created",
            {
                "research_id": "plan-1",
                "question": "How should effort be allocated?",
                "hypotheses": ["Parallelism improves throughput", "Retries improve quality"],
                "unresolved_questions": ["How can parallelism be measured?"],
            },
        ),
        _event(
            "research_evidence_added",
            {
                "evidence_id": "e-1",
                "kind": "experiment",
                "claim": "Parallel branches reduce elapsed time.",
                "content": "A deterministic benchmark showed lower latency.",
                "supports_hypothesis": "Parallelism improves throughput",
                "confidence": 0.8,
                "refs": ["artifact://benchmark"],
            },
            sequence=2,
        ),
    ]

    projection = research_evidence_from_events(events)

    assert projection["summary"] == {
        "evidence_count": 1,
        "hypothesis_count": 2,
        "covered_hypothesis_count": 1,
        "coverage": 0.5,
        "average_confidence": 0.8,
    }
    assert projection["hypotheses"][0]["evidence_ids"] == ["e-1"]
    assert projection["unresolved_questions"] == ["How can parallelism be measured?"]


def test_research_evidence_request_rejects_invalid_confidence_and_secrets():
    with pytest.raises(ValueError):
        ResearchEvidenceRequest(
            kind="observation",
            claim="A claim",
            content="Some evidence",
            confidence=1.1,
        )
    with pytest.raises(ValueError):
        ResearchEvidenceRequest(
            kind="observation",
            claim="A claim",
            content="token=super-secret-value",
        )
