from __future__ import annotations

import asyncio
from typing import Any

from app.audit.validator import audit_claims, audit_tool_results
from app.events.models import ArtifactRecord, AuditVerdict, ToolExecutionRecord
from app.tools.base import ToolResult


class Auditor:
    def __init__(self, llm: Any | None = None, llm_timeout_seconds: float = 60.0) -> None:
        self.llm = llm
        self.llm_timeout_seconds = llm_timeout_seconds

    def audit_tool_results(
        self,
        tool_results: list[ToolResult | ToolExecutionRecord | dict[str, Any]],
        worker_summary: str,
    ) -> AuditVerdict:
        return audit_tool_results(tool_results, worker_summary)

    async def audit_tool_results_with_model(
        self,
        tool_results: list[ToolResult | ToolExecutionRecord | dict[str, Any]],
        worker_summary: str,
        model_summaries: list[dict[str, Any]] | None = None,
    ) -> tuple[AuditVerdict, dict[str, Any] | None, dict[str, Any], str | None]:
        model_response = await self._review_with_model(
            tool_results=tool_results,
            worker_summary=worker_summary,
            model_summaries=model_summaries or [],
        )
        return (
            self.audit_tool_results(tool_results, worker_summary),
            model_response.get("thinking_summary_delta"),
            model_response.get("model_message", {}),
            model_response.get("raw_reasoning_content"),
        )

    def audit_claims(
        self,
        required_artifacts: list[str],
        artifacts: list[ArtifactRecord | dict[str, Any]],
        thinking_deltas: list[dict[str, Any]],
    ) -> AuditVerdict:
        return audit_claims(required_artifacts, artifacts, thinking_deltas)

    async def _review_with_model(
        self,
        *,
        tool_results: list[ToolResult | ToolExecutionRecord | dict[str, Any]],
        worker_summary: str,
        model_summaries: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if self.llm is None or not hasattr(self.llm, "complete_json"):
            return {}
        normalized_tool_results = [
            result.model_dump(mode="json") if hasattr(result, "model_dump") else result
            for result in tool_results
        ]
        prompt = (
            "Audit the worker result using only public summaries and tool evidence.\n"
            f"Worker summary: {worker_summary}\n"
            f"Model summaries: {model_summaries}\n"
            f"Tool results: {normalized_tool_results}\n"
            "Return JSON with a public thinking_summary_delta and answer."
        )
        response = await asyncio.wait_for(
            self.llm.complete_json(prompt, schema_name="audit_verdict"),
            timeout=self.llm_timeout_seconds,
        )
        return response if isinstance(response, dict) else {}
