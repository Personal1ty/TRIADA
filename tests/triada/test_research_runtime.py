import pytest

from app.research.plan import build_research_plan
from app.schemas.tasks import ResearchPlanRequest


def test_research_plan_expands_parameters_into_why_and_how_questions():
    plan = build_research_plan(
        question="How should the swarm allocate research effort?",
        parameter_catalog=["parallelism", "latency"],
        hypotheses=["More parallelism improves coverage"],
        depth=2,
    )

    assert plan["question"] == "How should the swarm allocate research effort?"
    assert plan["parameter_catalog"] == ["parallelism", "latency"]
    assert plan["why_questions"] == [
        "Why does parallelism matter for: How should the swarm allocate research effort?",
        "Why does latency matter for: How should the swarm allocate research effort?",
    ]
    assert plan["how_questions"] == [
        "How can parallelism be measured or changed?",
        "How can latency be measured or changed?",
    ]
    assert plan["unresolved_questions"]


def test_research_request_rejects_empty_parameter_catalog():
    with pytest.raises(ValueError):
        ResearchPlanRequest(question="Why?", parameter_catalog=[])
