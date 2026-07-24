from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.agents.auditor import Auditor
from app.agents.orchestrator import LLMUnavailableError, Orchestrator, PlanStep, TaskPlan
from app.agents.worker import Worker, WorkerResult
from app.config import get_settings
from app.contracts.loader import load_default_swarm_contract
from app.contracts.swarm import AgentEndpoint, RouteMapEntry
from app.events.models import ToolExecutionRecord
from app.llm.codex_bridge import CodexBridgeProvider
from app.llm.fake import FakeLLMProvider
from app.llm.openai_compatible import OpenAICompatibleProvider
from app.llm.openai_responses import OpenAIResponsesProvider
from app.schemas.enums import AgentRole, AuditVerdictValue, DeltaSource


class ExecutionEngine:
    def __init__(
        self,
        *,
        emitter: Any,
        workspace: str | Path,
        orchestrator: Orchestrator | None = None,
        auditor: Auditor | None = None,
        worker_id: str = "worker-1",
    ) -> None:
        self._emitter = emitter
        self._workspace = Path(workspace).resolve()
        self._llm = orchestrator.llm if orchestrator is not None else self._build_llm_provider()
        self._orchestrator = orchestrator or Orchestrator(self._llm)
        self._auditor = auditor or Auditor(self._llm)
        if getattr(self._auditor, "llm", None) is None:
            self._auditor.llm = self._llm
        self._worker_id = worker_id
        self._swarm_contract = load_default_swarm_contract()

    async def run_once(self, task: Any) -> str:
        await self._emit(task, "planning_started", {"goal": task.goal})
        await self._emit_delta(
            task,
            agent_id="orchestrator",
            agent_role=AgentRole.ORCHESTRATOR,
            stage="planning",
            action="plan_task",
            summary="Orchestrator started building a bounded task plan.",
            progress_percent=10,
        )
        try:
            plan = await self._orchestrator.plan_task(
                task.goal,
                task.allowed_tools,
                task.acceptance_criteria,
            )
        except LLMUnavailableError as exc:
            await self._emit(
                task,
                "llm_unavailable",
                {
                    "status": "blocked",
                    "provider": type(self._orchestrator.llm).__name__,
                    "reason": str(exc),
                },
            )
            return "blocked"
        await self._emit_plan_created(task, plan)
        model_summaries: list[dict[str, Any]] = []
        if plan.model_thinking_summary_delta:
            model_summaries.append(plan.model_thinking_summary_delta)
            await self._emit_model_delta(
                task,
                agent_id="orchestrator",
                agent_role=AgentRole.ORCHESTRATOR,
                delta=plan.model_thinking_summary_delta,
                model_message=plan.model_message,
            )
        if plan.raw_reasoning_content:
            await self._emit_model_reasoning_content(
                task,
                agent_id="orchestrator",
                agent_role=AgentRole.ORCHESTRATOR,
                schema_name="plan",
                raw_reasoning_content=plan.raw_reasoning_content,
            )

        if plan.requires_approval and not self._is_approved(task):
            await self._emit(
                task,
                "approval_required",
                {
                    "status": "waiting_approval",
                    "risk_policy": plan.risk_policy.value,
                    "steps": [step.model_dump(mode="json") for step in plan.steps],
                },
            )
            return "waiting_approval"

        worker = Worker(worker_id=self._worker_id, workspace=self._workspace, llm=self._llm)
        worker_results: list[WorkerResult] = []
        tool_records: list[ToolExecutionRecord] = []
        final_status = "completed"

        for step in plan.steps:
            command = self._command_for_step(step)
            await self._emit_route(
                task,
                source=AgentEndpoint.ORCHESTRATOR,
                target=AgentEndpoint.WORKER,
                reason="assign_step",
                agent_id="orchestrator",
            )
            await self._emit(task, "worker_step_started", {"step_id": step.id, "title": step.title, "command": command})
            await self._emit_delta(
                task,
                agent_id=self._worker_id,
                agent_role=AgentRole.WORKER,
                stage="execution",
                action="run_step",
                summary=f"Worker started step {step.id}.",
                input_refs=[f"plan_step:{step.id}"],
                progress_percent=40,
            )
            result = await worker.run_step(
                task_id=str(task.id),
                step_id=step.id,
                title=step.title,
                allowed_tools=step.allowed_tools,
                command=command,
                risk_policy=step.risk_policy,
                approval_ref=self._approval_ref(task),
            )
            worker_results.append(result)
            if result.model_thinking_summary_delta:
                model_summaries.append(result.model_thinking_summary_delta)
                await self._emit_model_delta(
                    task,
                    agent_id=self._worker_id,
                    agent_role=AgentRole.WORKER,
                    delta=result.model_thinking_summary_delta,
                    model_message=result.model_message,
                )
            if result.raw_reasoning_content:
                await self._emit_model_reasoning_content(
                    task,
                    agent_id=self._worker_id,
                    agent_role=AgentRole.WORKER,
                    schema_name="worker_result",
                    raw_reasoning_content=result.raw_reasoning_content,
                )
            tool_records.extend(result.tool_results)
            event_type = "worker_step_completed" if result.status == "succeeded" else f"worker_step_{result.status}"
            await self._emit(task, event_type, result.model_dump(mode="json"))
            for record in result.tool_results:
                await self._emit(task, "tool_execution_completed", record.model_dump(mode="json"), agent_id=self._worker_id)
            if result.status == "blocked":
                final_status = "blocked"
                break
            if result.status != "succeeded":
                final_status = "failed"
                break

        has_worker_evidence = any(result.status == "succeeded" for result in worker_results)
        if not has_worker_evidence:
            return final_status

        await self._emit_route(
            task,
            source=AgentEndpoint.WORKER,
            target=AgentEndpoint.ASSIGNED_AUDITOR,
            reason="submit_evidence",
            agent_id=self._worker_id,
        )
        (
            verdict,
            auditor_model_delta,
            auditor_model_message,
            auditor_raw_reasoning_content,
        ) = await self._auditor.audit_tool_results_with_model(
            tool_records,
            "\n".join(result.summary for result in worker_results),
            model_summaries,
        )
        if auditor_model_delta:
            await self._emit_model_delta(
                task,
                agent_id="auditor",
                agent_role=AgentRole.AUDITOR,
                delta=auditor_model_delta,
                model_message=auditor_model_message,
            )
        if auditor_raw_reasoning_content:
            await self._emit_model_reasoning_content(
                task,
                agent_id="auditor",
                agent_role=AgentRole.AUDITOR,
                schema_name="audit_verdict",
                raw_reasoning_content=auditor_raw_reasoning_content,
            )
        await self._emit_delta(
            task,
            agent_id="auditor",
            agent_role=AgentRole.AUDITOR,
            stage="audit",
            action="audit_tool_results",
            summary="Auditor evaluated worker evidence.",
            progress_percent=90,
        )
        await self._emit(task, "audit_verdict", verdict.model_dump(mode="json"), agent_id="auditor")

        if final_status == "completed" and verdict.verdict != AuditVerdictValue.PASS:
            final_status = "corrections_required"
        return final_status

    async def _emit_plan_created(self, task: Any, plan: TaskPlan) -> None:
        await self._emit(
            task,
            "planning_completed",
            {
                "risk_policy": plan.risk_policy.value,
                "requires_approval": plan.requires_approval,
                "steps": [step.model_dump(mode="json") for step in plan.steps],
            },
        )

    async def _emit_delta(
        self,
        task: Any,
        *,
        agent_id: str,
        agent_role: AgentRole,
        stage: str,
        action: str,
        summary: str,
        input_refs: list[str] | None = None,
        output_refs: list[str] | None = None,
        progress_percent: int | None = None,
    ) -> None:
        payload = {
            "schema_version": "1.0",
            "agent_id": agent_id,
            "agent_role": agent_role.value,
            "source": DeltaSource.RUNTIME.value,
            "span_id": str(uuid4()),
            "stage": stage,
            "action": action,
            "summary": summary,
            "observations": [],
            "input_refs": input_refs or [],
            "output_refs": output_refs or [],
            "progress_percent": progress_percent,
            "created_at": datetime.now(UTC).isoformat(),
            "metadata": {},
        }
        await self._emit(task, "thinking_summary_delta", payload, agent_id=agent_id)

    async def _emit_route(
        self,
        task: Any,
        *,
        source: AgentEndpoint,
        target: AgentEndpoint,
        reason: str,
        agent_id: str,
    ) -> None:
        route = self._route_for(source=source, target=target, reason=reason)
        await self._emit(
            task,
            "swarm_route_selected",
            {
                "schema_version": "1.0",
                "source": route.source.value,
                "target": route.target.value,
                "reason": route.reason,
                "input_contract": route.input_contract.ref,
                "output_contract": route.output_contract.ref,
            },
            agent_id=agent_id,
        )

    def _route_for(
        self,
        *,
        source: AgentEndpoint,
        target: AgentEndpoint,
        reason: str,
    ) -> RouteMapEntry:
        for route in self._swarm_contract.route_map:
            if route.source == source and route.target == target and route.reason == reason:
                return route
        raise LookupError(f"swarm route not found: {source.value}->{target.value}/{reason}")

    async def _emit_model_delta(
        self,
        task: Any,
        *,
        agent_id: str,
        agent_role: AgentRole,
        delta: dict[str, Any],
        model_message: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "schema_version": "1.0",
            "agent_id": agent_id,
            "agent_role": agent_role.value,
            "source": DeltaSource.MODEL.value,
            "span_id": str(uuid4()),
            "stage": delta.get("stage", "model"),
            "action": delta.get("action", "complete_json"),
            "summary": delta.get("summary", "Model produced a public reasoning summary."),
            "observations": delta.get("observations", []),
            "input_refs": delta.get("input_refs", []),
            "output_refs": delta.get("output_refs", []),
            "next_step": delta.get("next_step"),
            "progress_percent": delta.get("progress_percent"),
            "confidence": delta.get("confidence"),
            "created_at": datetime.now(UTC).isoformat(),
            "metadata": {"model_message": model_message or {}},
        }
        await self._emit(task, "thinking_summary_delta", payload, agent_id=agent_id)

    async def _emit_model_reasoning_content(
        self,
        task: Any,
        *,
        agent_id: str,
        agent_role: AgentRole,
        schema_name: str,
        raw_reasoning_content: str,
    ) -> None:
        await self._emit(
            task,
            "model_reasoning_content_captured",
            {
                "schema_version": "1.0",
                "agent_id": agent_id,
                "agent_role": agent_role.value,
                "source": DeltaSource.MODEL.value,
                "schema_name": schema_name,
                "raw_reasoning_content": raw_reasoning_content,
                "captured_at": datetime.now(UTC).isoformat(),
                "metadata": {"sensitive": True},
            },
            agent_id=agent_id,
        )

    async def _emit(self, task: Any, event_type: str, payload: dict[str, Any], *, agent_id: str = "orchestrator") -> None:
        await self._emitter.emit(
            event_type=event_type,
            trace_id=task.trace_id,
            task_id=task.id,
            agent_id=agent_id,
            payload=payload,
        )

    def _command_for_step(self, step: PlanStep) -> list[str]:
        if "git" in step.allowed_tools:
            return ["git", "status"]
        if "shell" in step.allowed_tools:
            return ["echo", step.description]
        return []

    def _build_llm_provider(self):
        settings = get_settings()
        if settings.llm_provider == "openai-compatible":
            return OpenAICompatibleProvider(
                base_url=settings.llm_base_url,
                api_key=(
                    settings.llm_api_key.get_secret_value()
                    if settings.llm_api_key is not None
                    else None
                ),
                model=settings.llm_model,
            )
        if settings.llm_provider == "openai-responses":
            return OpenAIResponsesProvider(
                base_url=settings.llm_base_url,
                api_key=(
                    settings.llm_api_key.get_secret_value()
                    if settings.llm_api_key is not None
                    else None
                ),
                model=settings.llm_model,
            )
        if settings.llm_provider == "codex-bridge":
            return CodexBridgeProvider()
        return FakeLLMProvider()

    def _is_approved(self, task: Any) -> bool:
        approval = getattr(task, "metadata", {}).get("approval", {})
        return bool(approval.get("approved"))

    def _approval_ref(self, task: Any) -> str | None:
        approval = getattr(task, "metadata", {}).get("approval", {})
        if not approval.get("approved"):
            return None
        return str(approval.get("approved_by") or "approved")
