from app.contracts.normalizer import ContractNormalizer
from app.contracts.research import ResearchMode


def test_normalizer_canonicalizes_malformed_llm_research_draft():
    contract = ContractNormalizer().research(
        {
            "mode": "research",
            "research_questions": "compare the roles",
            "depth": 2,
            "required_evidence": "tool_execution",
            "required_artifacts": {"name": "research_report"},
            "output_schema": {"type": "object"},
            "min_tool_executions": "3",
            "unknown_model_field": "ignore me",
        },
        goal="Analyze TRIADA",
        acceptance_criteria=["return findings"],
    )

    assert contract.mode == ResearchMode.RESEARCH
    assert contract.research_questions == ["compare the roles"]
    assert contract.depth == "2"
    assert contract.required_evidence == ["tool_execution"]
    assert contract.required_artifacts == ["research_report"]
    assert contract.output_schema == "research_report"
    assert contract.min_tool_executions == 3


def test_normalizer_uses_safe_defaults_for_invalid_semantic_values():
    contract = ContractNormalizer().research(
        {"mode": "dangerous", "min_tool_executions": -5},
        goal="Analyze TRIADA",
        acceptance_criteria=[],
    )

    assert contract.mode == ResearchMode.RESEARCH
    assert contract.min_tool_executions == 3


def test_normalizer_accepts_non_research_draft_without_forcing_research():
    contract = ContractNormalizer().research(
        {"mode": "none", "required_artifacts": ["unexpected"]},
        goal="List files",
        acceptance_criteria=[],
    )

    assert contract.mode == ResearchMode.NONE
    assert contract.required_artifacts == []
