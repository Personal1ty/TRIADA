from __future__ import annotations

from typing import Any

from app.audit.validator import audit_claims, audit_tool_results
from app.events.models import ArtifactRecord, AuditVerdict
from app.tools.base import ToolResult


class Auditor:
    def audit_tool_results(
        self,
        tool_results: list[ToolResult | dict[str, Any]],
        worker_summary: str,
    ) -> AuditVerdict:
        return audit_tool_results(tool_results, worker_summary)

    def audit_claims(
        self,
        required_artifacts: list[str],
        artifacts: list[ArtifactRecord | dict[str, Any]],
        thinking_deltas: list[dict[str, Any]],
    ) -> AuditVerdict:
        return audit_claims(required_artifacts, artifacts, thinking_deltas)
