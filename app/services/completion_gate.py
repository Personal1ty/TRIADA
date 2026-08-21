from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.contracts.research import ResearchContract, ResearchMode
from app.schemas.enums import AuditVerdictValue


@dataclass(frozen=True)
class CompletionDecision:
    passed: bool
    reason: str
    missing_artifacts: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    next_action: str = "stop"


class CompletionGate:
    def evaluate(
        self,
        contract: ResearchContract | dict[str, Any],
        *,
        worker_results: list[Any],
        tool_records: list[Any],
        verdicts: list[tuple[str, Any]],
    ) -> CompletionDecision:
        contract = ResearchContract.model_validate(contract)
        if contract.mode == ResearchMode.NONE:
            return CompletionDecision(True, "standard_contract_satisfied")

        artifact_names = {
            artifact.name
            for result in worker_results
            for artifact in self._artifacts_from(result)
        }
        missing_artifacts = [
            name for name in contract.required_artifacts if name not in artifact_names
        ]
        missing_evidence = []
        if len(tool_records) < contract.min_tool_executions:
            missing_evidence.append(
                f"tool_executions>={contract.min_tool_executions}"
            )
        if contract.required_evidence and not tool_records:
            missing_evidence.extend(contract.required_evidence)
        if any(verdict.verdict != AuditVerdictValue.PASS for _, verdict in verdicts):
            missing_evidence.append("passing_audit_verdict")
        passed = not missing_artifacts and not missing_evidence
        return CompletionDecision(
            passed=passed,
            reason="research_contract_satisfied" if passed else "research_contract_not_satisfied",
            missing_artifacts=missing_artifacts,
            missing_evidence=missing_evidence,
            next_action="stop" if passed else "replan_research",
        )

    def _artifacts_from(self, result: Any) -> list[Any]:
        if isinstance(result, dict):
            return result.get("artifacts", [])
        return getattr(result, "artifacts", [])
