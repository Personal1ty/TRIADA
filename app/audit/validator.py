from __future__ import annotations

from typing import Any

from app.events.models import ArtifactRecord, AuditVerdict, AuditViolation, ToolExecutionRecord
from app.schemas.enums import AuditVerdictValue
from app.tools.base import ToolResult


def audit_tool_results(
    tool_results: list[ToolResult | ToolExecutionRecord | dict[str, Any]],
    worker_summary: str,
) -> AuditVerdict:
    violations: list[AuditViolation] = []
    normalized_summary = worker_summary.lower()
    parsed_results = [_as_tool_result(result) for result in tool_results]

    for result in parsed_results:
        reports_failure = _summary_reports_failure(normalized_summary, result.exit_code)
        if result.exit_code != 0 and reports_failure and _summary_claims_success(normalized_summary):
            violations.append(
                AuditViolation(
                    rule_id="SUMMARY_CONTRADICTS_TOOL_RESULT",
                    message=f"Worker summary claims success despite {result.tool} exit code {result.exit_code}.",
                    metadata={"tool": result.tool, "command": result.command},
                )
            )
        if result.exit_code != 0 and not reports_failure:
            violations.append(
                AuditViolation(
                    rule_id="TOOL_FAILURE_NOT_REPORTED",
                    message=f"Tool failure from {result.tool} exit code {result.exit_code} was not reported.",
                    metadata={"tool": result.tool, "command": result.command},
                )
            )

    if _summary_claims_success(normalized_summary) and not parsed_results:
        violations.append(
            AuditViolation(
                rule_id="SUCCESS_CLAIM_WITHOUT_EVIDENCE",
                message="Worker summary claims success without supporting tool results or evidence.",
            )
        )

    return _verdict(violations)


def audit_claims(
    required_artifacts: list[str],
    artifacts: list[ArtifactRecord | dict[str, Any]],
    thinking_deltas: list[dict[str, Any]],
) -> AuditVerdict:
    del thinking_deltas
    violations: list[AuditViolation] = []
    artifact_refs = {_artifact_ref(artifact) for artifact in artifacts}

    for required in required_artifacts:
        if required not in artifact_refs:
            violations.append(
                AuditViolation(
                    rule_id="REQUIRED_ARTIFACT_MISSING",
                    message=f"Required artifact '{required}' is missing.",
                    metadata={"required_artifact": required},
                )
            )

    return _verdict(violations)


def _as_tool_result(result: ToolResult | ToolExecutionRecord | dict[str, Any]) -> ToolResult | ToolExecutionRecord:
    if isinstance(result, ToolResult):
        return result
    if isinstance(result, ToolExecutionRecord):
        return result
    return ToolResult.model_validate(result)


def _artifact_ref(artifact: ArtifactRecord | dict[str, Any]) -> str:
    record = artifact if isinstance(artifact, ArtifactRecord) else ArtifactRecord.model_validate(artifact)
    return record.name if record.name else record.path or ""


def _summary_reports_failure(summary: str, exit_code: int) -> bool:
    failure_terms = ("fail", "failed", "failure", "error", "non-zero", "nonzero")
    return any(term in summary for term in failure_terms) or f"exit code {exit_code}" in summary


def _summary_claims_success(summary: str) -> bool:
    success_terms = ("success", "succeeded", "completed", "done", "passed")
    return any(term in summary for term in success_terms)


def _verdict(violations: list[AuditViolation]) -> AuditVerdict:
    if violations:
        return AuditVerdict(
            verdict=AuditVerdictValue.CORRECTIONS_REQUIRED,
            summary="Corrections are required.",
            violations=violations,
            required_corrections=[violation.message for violation in violations],
        )
    return AuditVerdict(verdict=AuditVerdictValue.PASS, summary="Audit passed.")
