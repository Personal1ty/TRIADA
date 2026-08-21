from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.agents.auditor import Auditor
from app.agents.orchestrator import LLMUnavailableError, Orchestrator, PlanStep, TaskPlan
from app.agents.worker import Worker, WorkerResult
from app.config import get_settings
from app.contracts.execution import ResourceBudgetContract
from app.contracts.loader import load_default_swarm_contract
from app.contracts.swarm import AgentEndpoint, RouteMapEntry, SwarmContract
from app.events.models import AuditVerdict, ToolExecutionRecord
from app.llm.codex_bridge import CodexBridgeProvider
from app.llm.fake import FakeLLMProvider
from app.llm.openai_compatible import OpenAICompatibleProvider
from app.llm.openai_responses import OpenAIResponsesProvider
from app.llm.runtime_config import LLMConfigService
from app.schemas.enums import AgentRole, AuditVerdictValue, DeltaSource
from app.services.scheduler import BoundedStepScheduler
from app.services.resource_budget import ResourceBudget, ResourceUsage, allocate_work
from app.services.swarm_scaling import choose_scaling
from app.services.policy_gate import PolicyContractError, PolicyGate
from app.services.completion_gate import CompletionGate


class ExecutionEngine:
    def __init__(
        self,
        *,
        emitter: Any,
        workspace: str | Path,
        orchestrator: Orchestrator | None = None,
        auditor: Auditor | None = None,
        worker_id: str = "worker-1",
        llm_config_service: LLMConfigService | None = None,
        worker_llm_timeout_seconds: float | None = None,
        orchestrator_llm_timeout_seconds: float | None = None,
        auditor_llm_timeout_seconds: float | None = None,
    ) -> None:
        self._emitter = emitter
        self._workspace = Path(workspace).resolve()
        self._llm_config_service = llm_config_service
        self._owns_agents = orchestrator is None
        self._llm = orchestrator.llm if orchestrator is not None else self._build_llm_provider()
        self._orchestrator = orchestrator or Orchestrator(self._llm)
        self._auditor = auditor or Auditor(self._llm)
        if getattr(self._auditor, "llm", None) is None:
            self._auditor.llm = self._llm
        self._worker_id = worker_id
        self._worker_llm_timeout_seconds = (
            worker_llm_timeout_seconds
            if worker_llm_timeout_seconds is not None
            else get_settings().worker_llm_timeout_seconds
        )
        settings = get_settings()
        self._orchestrator_llm_timeout_seconds = (
            orchestrator_llm_timeout_seconds
            if orchestrator_llm_timeout_seconds is not None
            else getattr(self._orchestrator, "llm_timeout_seconds", settings.orchestrator_llm_timeout_seconds)
        )
        self._auditor_llm_timeout_seconds = (
            auditor_llm_timeout_seconds
            if auditor_llm_timeout_seconds is not None
            else getattr(self._auditor, "llm_timeout_seconds", settings.auditor_llm_timeout_seconds)
        )
        self._orchestrator.llm_timeout_seconds = self._orchestrator_llm_timeout_seconds
        self._auditor.llm_timeout_seconds = self._auditor_llm_timeout_seconds
        self._swarm_contract = load_default_swarm_contract()
        self._policy_gate = PolicyGate()
        self._completion_gate = CompletionGate()

    def set_swarm_contract(self, contract: SwarmContract) -> None:
        self._swarm_contract = contract

    async def run_once(self, task: Any) -> str:
        if self._owns_agents:
            self._llm = self._build_llm_provider()
            self._orchestrator.llm = self._llm
            self._auditor.llm = self._llm
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
        plan = self._pending_plan(task) if self._is_approved(task) else None
        if plan is not None:
            await self._emit(task, "planning_reused", {"source": "pending_approved_plan"})
        else:
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
        try:
            plan = self._apply_execution_contract(task, plan)
        except PolicyContractError as exc:
            await self._emit(
                task,
                "execution_contract_rejected",
                {"status": "blocked", "reason": str(exc)},
                agent_id="orchestrator",
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
            self._store_pending_plan(task, plan)
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
        self._clear_pending_plan(task)

        worker_results: list[WorkerResult] = []
        tool_records: list[ToolExecutionRecord] = []
        final_status = "completed"
        verdicts = []
        retry_limit = int(getattr(task, "retry_limit", 0) or 0)
        attempt = 0

        while True:
            attempt += 1
            attempt_results = await self._run_plan_steps(task, plan, model_summaries, attempt=attempt)
            worker_results.extend(attempt_results)
            attempt_tool_records = [record for result in attempt_results for record in result.tool_results]
            tool_records.extend(attempt_tool_records)

            if any(result.status == "blocked" for result in attempt_results):
                final_status = "blocked"
                break
            final_status = "failed" if any(result.status != "succeeded" for result in attempt_results) else "completed"
            if not attempt_tool_records:
                break

            verdicts = await self._audit_worker_results(task, attempt_results, model_summaries)
            if final_status == "completed" and any(
                verdict.verdict != AuditVerdictValue.PASS for _auditor_id, verdict in verdicts
            ):
                final_status = (
                    "failed"
                    if any(verdict.verdict == AuditVerdictValue.FAIL for _auditor_id, verdict in verdicts)
                    else "corrections_required"
                )
            if final_status != "corrections_required" or attempt > retry_limit:
                break
            for auditor_id, verdict in verdicts:
                if verdict.verdict != AuditVerdictValue.PASS:
                    await self._emit_route(
                        task,
                        source=AgentEndpoint.ASSIGNED_AUDITOR,
                        target=AgentEndpoint.WORKER,
                        reason="request_correction",
                        agent_id=auditor_id,
                        source_agent_id=auditor_id,
                        target_agent_id=self._worker_id_for_auditor(auditor_id),
                    )
                    await self._emit(
                        task,
                        "correction_requested",
                        {
                            "schema_version": "1.0",
                            "attempt": attempt,
                            "max_attempts": retry_limit + 1,
                            "auditor_id": auditor_id,
                            "summary": verdict.summary,
                            "required_corrections": verdict.required_corrections,
                        },
                        agent_id=auditor_id,
                    )
            final_status = "retrying"

        if final_status == "completed":
            completion = self._completion_gate.evaluate(
                plan.research_contract,
                worker_results=worker_results,
                tool_records=tool_records,
                verdicts=verdicts,
            )
            if not completion.passed:
                await self._emit(
                    task,
                    "completion_gate_failed",
                    {
                        "status": "failed",
                        "reason": completion.reason,
                        "missing_artifacts": completion.missing_artifacts,
                        "missing_evidence": completion.missing_evidence,
                        "next_action": completion.next_action,
                    },
                    agent_id="orchestrator",
                )
                final_status = "failed"

        if final_status == "blocked" or not tool_records:
            return final_status

        chief_auditor_id = self._swarm_contract.topology.chief_auditor.agent_id
        chief_verdict = self._chief_verdict_value(final_status, verdicts)
        chief_summary = self._chief_verdict_summary(verdicts)
        await self._emit_route(
            task,
            source=AgentEndpoint.ASSIGNED_AUDITOR,
            target=AgentEndpoint.CHIEF_AUDITOR,
            reason="escalate_verdict",
            agent_id=verdicts[-1][0] if verdicts else self._assigned_auditor_id_for_worker(self._worker_id),
            source_agent_id=verdicts[-1][0] if verdicts else self._assigned_auditor_id_for_worker(self._worker_id),
            target_agent_id=chief_auditor_id,
        )
        await self._emit(
            task,
            "chief_audit_verdict",
            {
                "schema_version": "1.0",
                "chief_auditor_id": chief_auditor_id,
                "verdict": chief_verdict,
                "source_verdict_refs": ["audit_verdict"],
                "summary": chief_summary,
                "agent_id": chief_auditor_id,
            },
            agent_id=chief_auditor_id,
        )
        await self._emit_route(
            task,
            source=AgentEndpoint.CHIEF_AUDITOR,
            target=AgentEndpoint.ORCHESTRATOR,
            reason="return_final_gate",
            agent_id=chief_auditor_id,
            source_agent_id=chief_auditor_id,
            target_agent_id="orchestrator",
        )
        await self._emit(
            task,
            "human_review_packet_created",
            {
                "schema_version": "1.0",
                "contract": {"name": "human_review_packet", "version": "1.0"},
                "status": final_status,
                "chief_auditor_verdict": chief_verdict,
                "summary": chief_summary,
                "worker_result_count": len(worker_results),
                "tool_result_count": len(tool_records),
                "raw_reasoning_refs": [],
                "agent_id": "orchestrator",
            },
        )
        await self._emit_route(
            task,
            source=AgentEndpoint.ORCHESTRATOR,
            target=AgentEndpoint.HUMAN,
            reason="deliver_human_packet",
            agent_id="orchestrator",
            source_agent_id="orchestrator",
            target_agent_id="human",
        )
        return final_status

    async def _run_plan_steps(
        self,
        task: Any,
        plan: TaskPlan,
        model_summaries: list[dict[str, Any]],
        *,
        attempt: int = 1,
    ) -> list[WorkerResult]:
        scaling = choose_scaling(
            self._swarm_contract,
            step_count=len(plan.steps),
            risk_policy=plan.risk_policy.value,
        )
        await self._emit(
            task,
            "swarm_scaled",
            {
                "weight": scaling.weight,
                "requested_pairs": scaling.requested_pairs,
                "selected_worker_ids": scaling.selected_worker_ids,
                "selected_auditor_ids": scaling.selected_auditor_ids,
                "step_count": len(plan.steps),
                "risk_policy": plan.risk_policy.value,
                "reason": scaling.reason,
            },
        )
        active_pairs = self._active_pairs(scaling.selected_worker_ids)
        jobs = [
            (self._worker_id_for_step(index, active_pairs), step)
            for index, step in enumerate(plan.steps)
        ]
        if not jobs:
            return []

        budget = ResourceBudget(**plan.execution_contract.resource_budget.model_dump())
        admitted_jobs: list[tuple[str, PlanStep]] = []
        for job in jobs:
            decision = allocate_work(
                budget,
                ResourceUsage(
                    active_branches=len(admitted_jobs),
                    retries=max(0, attempt - 1),
                    tokens_used=0,
                ),
            )
            await self._emit(
                task,
                "resource_allocation_decided",
                {
                    "schema_version": "1.0",
                    "admitted": decision.admitted,
                    "reason": decision.reason,
                    "worker_id": job[0],
                    "step_id": job[1].id,
                    "attempt": attempt,
                    "budget": {
                        "max_parallel_branches": budget.max_parallel_branches,
                        "max_retries": budget.max_retries,
                        "max_tokens": budget.max_tokens,
                        "max_duration_ms": budget.max_duration_ms,
                    },
                    "usage": {
                        "active_branches": len(admitted_jobs),
                        "retries": max(0, attempt - 1),
                        "tokens_used": 0,
                        "duration_ms": 0,
                    },
                },
            )
            if decision.admitted:
                admitted_jobs.append(job)
        jobs = admitted_jobs
        if not jobs:
            return []

        worker_limits = {
            pair.worker_id: pair.max_parallel_steps
            for pair in active_pairs
        }
        max_concurrency = max(1, sum(worker_limits.values()))
        scheduler = BoundedStepScheduler(
            max_concurrency=max_concurrency,
            worker_limits=worker_limits,
        )

        async def run_job(job: tuple[str, PlanStep]) -> WorkerResult:
            worker_id, step = job
            return await self._run_worker_step(
                task=task,
                step=step,
                worker_id=worker_id,
                model_summaries=model_summaries,
            )

        return await scheduler.run(jobs, worker_key=lambda job: job[0], run=run_job)

    def _apply_execution_contract(self, task: Any, plan: TaskPlan) -> TaskPlan:
        raw_budget = getattr(task, "metadata", {}).get("resource_budget", {})
        task_budget = (
            ResourceBudgetContract.model_validate(raw_budget)
            if isinstance(raw_budget, dict)
            else ResourceBudgetContract()
        )
        proposal = plan.execution_contract.model_copy(update={"resource_budget": task_budget})
        effective_contract = self._policy_gate.enforce(
            proposal,
            task_allowed_tools=task.allowed_tools,
            risk_policy=plan.risk_policy,
        )
        requires_approval = plan.requires_approval or effective_contract.approval_required
        steps = [
            step.model_copy(update={"requires_approval": requires_approval})
            for step in plan.steps
        ]
        return plan.model_copy(
            update={
                "execution_contract": effective_contract,
                "requires_approval": requires_approval,
                "steps": steps,
            }
        )

    async def _run_worker_step(
        self,
        *,
        task: Any,
        step: PlanStep,
        worker_id: str,
        model_summaries: list[dict[str, Any]],
    ) -> WorkerResult:
        worker = Worker(
            worker_id=worker_id,
            workspace=self._workspace,
            llm=self._llm,
            llm_timeout_seconds=self._worker_llm_timeout_seconds,
        )
        command = self._command_for_step(step)
        await self._emit_route(
            task,
            source=AgentEndpoint.ORCHESTRATOR,
            target=AgentEndpoint.WORKER,
            reason="assign_step",
            agent_id="orchestrator",
            source_agent_id="orchestrator",
            target_agent_id=worker_id,
        )
        await self._emit(
            task,
            "worker_step_started",
            {"step_id": step.id, "title": step.title, "command": command, "worker_id": worker_id},
            agent_id=worker_id,
        )
        await self._emit_delta(
            task,
            agent_id=worker_id,
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
        if result.model_thinking_summary_delta:
            model_summaries.append(result.model_thinking_summary_delta)
            await self._emit_model_delta(
                task,
                agent_id=worker_id,
                agent_role=AgentRole.WORKER,
                delta=result.model_thinking_summary_delta,
                model_message=result.model_message,
            )
        if result.raw_reasoning_content:
            await self._emit_model_reasoning_content(
                task,
                agent_id=worker_id,
                agent_role=AgentRole.WORKER,
                schema_name="worker_result",
                raw_reasoning_content=result.raw_reasoning_content,
            )
        event_type = "worker_step_completed" if result.status == "succeeded" else f"worker_step_{result.status}"
        await self._emit(task, event_type, result.model_dump(mode="json"), agent_id=worker_id)
        for record in result.tool_results:
            await self._emit(task, "tool_execution_completed", record.model_dump(mode="json"), agent_id=worker_id)
        return result

    async def _audit_worker_results(
        self,
        task: Any,
        worker_results: list[WorkerResult],
        model_summaries: list[dict[str, Any]],
    ):
        verdicts = []
        for result in worker_results:
            if not result.tool_results:
                continue
            assigned_auditor_id = self._assigned_auditor_id_for_worker(result.worker_id)
            await self._emit_route(
                task,
                source=AgentEndpoint.WORKER,
                target=AgentEndpoint.ASSIGNED_AUDITOR,
                reason="submit_evidence",
                agent_id=result.worker_id,
                source_agent_id=result.worker_id,
                target_agent_id=assigned_auditor_id,
            )
            try:
                (
                    verdict,
                    auditor_model_delta,
                    auditor_model_message,
                    auditor_raw_reasoning_content,
                ) = await self._auditor.audit_tool_results_with_model(
                    result.tool_results,
                    result.summary,
                    model_summaries,
                )
            except TimeoutError as exc:
                verdict = AuditVerdict(
                    verdict=AuditVerdictValue.FAIL,
                    summary=f"Auditor LLM timed out: {exc}",
                )
                auditor_model_delta = None
                auditor_model_message = {}
                auditor_raw_reasoning_content = None
                await self._emit(
                    task,
                    "audit_failed",
                    {
                        "status": "failed",
                        "reason": "auditor_llm_timeout",
                        "message": f"Auditor LLM timed out after {self._auditor_llm_timeout_seconds:g} seconds",
                    },
                    agent_id=assigned_auditor_id,
                )
            except Exception as exc:
                verdict = AuditVerdict(
                    verdict=AuditVerdictValue.FAIL,
                    summary=f"Auditor failed: {exc}",
                )
                auditor_model_delta = None
                auditor_model_message = {}
                auditor_raw_reasoning_content = None
                await self._emit(
                    task,
                    "audit_failed",
                    {
                        "status": "failed",
                        "reason": "auditor_llm_error",
                        "message": str(exc),
                    },
                    agent_id=assigned_auditor_id,
                )
            if auditor_model_delta:
                await self._emit_model_delta(
                    task,
                    agent_id=assigned_auditor_id,
                    agent_role=AgentRole.AUDITOR,
                    delta=auditor_model_delta,
                    model_message=auditor_model_message,
                )
            if auditor_raw_reasoning_content:
                await self._emit_model_reasoning_content(
                    task,
                    agent_id=assigned_auditor_id,
                    agent_role=AgentRole.AUDITOR,
                    schema_name="audit_verdict",
                    raw_reasoning_content=auditor_raw_reasoning_content,
                )
            await self._emit_delta(
                task,
                agent_id=assigned_auditor_id,
                agent_role=AgentRole.AUDITOR,
                stage="audit",
                action="audit_tool_results",
                summary="Auditor evaluated worker evidence.",
                progress_percent=90,
            )
            await self._emit(task, "audit_verdict", verdict.model_dump(mode="json"), agent_id=assigned_auditor_id)
            verdicts.append((assigned_auditor_id, verdict))
        return verdicts

    async def _emit_plan_created(self, task: Any, plan: TaskPlan) -> None:
        await self._emit(
            task,
            "planning_completed",
            {
                "risk_policy": plan.risk_policy.value,
                "requires_approval": plan.requires_approval,
                "execution_contract": plan.execution_contract.model_dump(mode="json"),
                "research_contract": plan.research_contract.model_dump(mode="json"),
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
        source_agent_id: str | None = None,
        target_agent_id: str | None = None,
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
                "source_agent_id": source_agent_id or route.source.value,
                "target_agent_id": target_agent_id or route.target.value,
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

    def _assigned_auditor_id_for_worker(self, worker_id: str) -> str:
        for pair in self._swarm_contract.worker_auditor_pairs:
            if pair.worker_id == worker_id:
                return pair.auditor_id
        raise LookupError(f"assigned auditor not found for worker: {worker_id}")

    def _worker_id_for_auditor(self, auditor_id: str) -> str:
        for pair in self._swarm_contract.worker_auditor_pairs:
            if pair.auditor_id == auditor_id:
                return pair.worker_id
        raise LookupError(f"assigned worker not found for auditor: {auditor_id}")

    def _worker_id_for_step(self, step_index: int, pairs=None) -> str:
        pairs = pairs or self._swarm_contract.worker_auditor_pairs
        if not pairs:
            return self._worker_id
        return pairs[step_index % len(pairs)].worker_id

    def _active_pairs(self, worker_ids: list[str]):
        selected = set(worker_ids)
        return [pair for pair in self._swarm_contract.worker_auditor_pairs if pair.worker_id in selected]

    def _chief_verdict_value(self, final_status: str, verdicts) -> str:
        if final_status == "completed" and verdicts:
            return AuditVerdictValue.PASS.value
        if verdicts:
            return verdicts[-1][1].verdict.value
        if final_status == "failed":
            return AuditVerdictValue.FAIL.value
        if final_status == "blocked":
            return AuditVerdictValue.BLOCKED.value
        return final_status

    def _chief_verdict_summary(self, verdicts) -> str:
        if verdicts:
            return verdicts[-1][1].summary
        return "No audit verdict was produced."

    async def _emit_model_delta(
        self,
        task: Any,
        *,
        agent_id: str,
        agent_role: AgentRole,
        delta: dict[str, Any] | str,
        model_message: dict[str, Any] | None = None,
    ) -> None:
        delta = self._normalize_model_delta(delta)
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

    def _normalize_model_delta(self, delta: dict[str, Any] | str) -> dict[str, Any]:
        if isinstance(delta, dict):
            return delta
        if isinstance(delta, str) and delta.strip():
            return {
                "stage": "model",
                "action": "complete_json",
                "summary": delta.strip(),
                "observations": [],
                "input_refs": [],
                "output_refs": [],
                "next_step": None,
                "progress_percent": None,
                "confidence": None,
            }
        return {}

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
        if step.command:
            return list(step.command)
        if "git" in step.allowed_tools:
            return ["git", "status"]
        if "pytest" in step.allowed_tools:
            return ["pytest", "-q"]
        if "rg" in step.allowed_tools:
            return ["rg", "--files"]
        if "ls" in step.allowed_tools:
            return ["ls"]
        if "cat" in step.allowed_tools:
            return ["cat", "README.md"]
        if "sed" in step.allowed_tools:
            return ["sed", "-n", "1,40p", "README.md"]
        if "write_file" in step.allowed_tools:
            return ["write_file", "triada-demo-output.txt", f"{step.description}\n"]
        if "mkdir" in step.allowed_tools:
            return ["mkdir", "-p", "triada-demo-output"]
        if "touch" in step.allowed_tools:
            return ["touch", "triada-demo-output.txt"]
        if "echo" in step.allowed_tools:
            return ["echo", step.description]
        if "shell" in step.allowed_tools:
            return ["echo", step.description]
        return []

    def _build_llm_provider(self):
        if self._llm_config_service is not None:
            config = self._llm_config_service.current_config()
            provider = config.provider
            base_url = config.base_url
            api_key = config.api_key
            model = config.model
        else:
            settings = get_settings()
            provider = settings.llm_provider
            base_url = settings.llm_base_url
            api_key = (
                settings.llm_api_key.get_secret_value()
                if settings.llm_api_key is not None
                else None
            )
            model = settings.llm_model

        if provider == "openai-compatible":
            return OpenAICompatibleProvider(
                base_url=base_url,
                api_key=api_key,
                model=model,
            )
        if provider == "openai-responses":
            return OpenAIResponsesProvider(
                base_url=base_url,
                api_key=api_key,
                model=model,
            )
        if provider == "codex-bridge":
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

    def _pending_plan(self, task: Any) -> TaskPlan | None:
        pending = getattr(task, "metadata", {}).get("pending_plan")
        if not isinstance(pending, dict):
            return None
        return TaskPlan.model_validate(pending)

    def _store_pending_plan(self, task: Any, plan: TaskPlan) -> None:
        metadata = getattr(task, "metadata", None)
        if isinstance(metadata, dict):
            metadata["pending_plan"] = plan.model_dump(mode="json")

    def _clear_pending_plan(self, task: Any) -> None:
        metadata = getattr(task, "metadata", None)
        if isinstance(metadata, dict):
            metadata.pop("pending_plan", None)
