from app.research.heuristics import build_analysis_adapter, build_design_adapter, build_research_adapter, derive_decision_heuristics


def test_heuristics_turn_observed_failures_and_usage_into_rules():
    rules = derive_decision_heuristics(
        failures=[{"category": "timeout"}],
        usage={"summary": {"tokens": 1200, "estimated_cost": 1.2}},
        quality_score=0.4,
    )

    assert [rule["rule"] for rule in rules] == ["timeout_guard", "cost_guard", "quality_guard"]


def test_research_adapter_is_bounded_and_declares_acceptance():
    adapter = build_research_adapter(question="How?", parameters=["risk", "latency"])

    assert adapter["adapter"] == "research"
    assert adapter["stages"][-1] == "audit_uncertainty"
    assert adapter["acceptance_criteria"]


def test_analysis_and_design_adapters_share_explicit_stage_contracts():
    assert build_analysis_adapter(question="Why?", parameters=["quality"])["adapter"] == "analysis"
    assert build_design_adapter(question="What?", parameters=["usability"])["adapter"] == "design"
