import pytest

pytest.importorskip("langgraph")

from app.runtime.langgraph_spike import run_research_subgraph


def test_research_subgraph_expands_and_audits_without_owning_triada_events():
    result, graph, config = run_research_subgraph(
        goal="Compare allocation strategies",
        question="Which strategy is safer?",
        parameter_catalog=["risk", "latency"],
        hypotheses=["Guardrails reduce risk"],
        evidence_refs=["artifact://benchmark"],
        thread_id="research-subgraph-test",
    )

    assert result["phase"] == "completed"
    assert result["plan"]["parameter_catalog"] == ["risk", "latency"]
    assert result["audit_summary"]
    assert graph.get_state(config).values["phase"] == "completed"
