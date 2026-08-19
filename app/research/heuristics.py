from __future__ import annotations

from typing import Any


def derive_decision_heuristics(*, failures: list[dict[str, Any]], usage: dict[str, Any], quality_score: float | None = None) -> list[dict[str, Any]]:
    heuristics = []
    categories = {str(item.get("category")) for item in failures}
    if "timeout" in categories:
        heuristics.append({"rule": "timeout_guard", "recommendation": "Bound tool duration before increasing parallelism.", "reason": "timeout pattern observed", "priority": "high"})
    summary = usage.get("summary", {}) if isinstance(usage, dict) else {}
    if summary.get("tokens", 0) >= 1_000 or summary.get("estimated_cost", 0) >= 1:
        heuristics.append({"rule": "cost_guard", "recommendation": "Prefer bounded branches and reuse memory before spawning new research.", "reason": "resource usage is high", "priority": "high"})
    if quality_score is not None and quality_score < 0.6:
        heuristics.append({"rule": "quality_guard", "recommendation": "Require an auditor checkpoint and add an unresolved question before completion.", "reason": "quality score is below 0.6", "priority": "medium"})
    return heuristics


def build_research_adapter(*, question: str, parameters: list[str]) -> dict[str, Any]:
    cleaned_question = question.strip()
    cleaned_parameters = [item.strip() for item in parameters if item.strip()]
    if not cleaned_question or not cleaned_parameters:
        raise ValueError("research adapter requires a question and parameters")
    return {
        "adapter": "research",
        "version": "1.0",
        "stages": ["frame_question", "catalog_parameters", "collect_evidence", "audit_uncertainty"],
        "question": cleaned_question,
        "parameters": cleaned_parameters,
        "required_capabilities": ["read_memory", "write_artifacts", "issue_verdict"],
        "acceptance_criteria": ["evidence is linked to a hypothesis", "unresolved questions are explicit"],
    }
