from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel, Field

from app.contracts.execution import ExecutionContract, WriteMode
from app.contracts.research import ResearchContract, ResearchMode
from app.schemas.enums import RiskPolicy


class StepContract(BaseModel):
    required_checks: list[str] = Field(default_factory=list)
    required_artifacts: list[str] = Field(default_factory=list)


class PlanStep(BaseModel):
    id: str
    title: str
    description: str
    allowed_tools: list[str] = Field(default_factory=list)
    command: list[str] = Field(default_factory=list)
    risk_policy: RiskPolicy = RiskPolicy.READ_ONLY
    requires_approval: bool = False
    output_contract: StepContract = Field(default_factory=StepContract)


class TaskPlan(BaseModel):
    goal: str
    steps: list[PlanStep] = Field(default_factory=list)
    output_contract: StepContract = Field(default_factory=StepContract)
    risk_policy: RiskPolicy = RiskPolicy.READ_ONLY
    requires_approval: bool = False
    execution_contract: ExecutionContract = Field(default_factory=ExecutionContract)
    research_contract: ResearchContract = Field(default_factory=ResearchContract)
    model_thinking_summary_delta: dict[str, Any] | None = None
    model_message: dict[str, Any] = Field(default_factory=dict)
    raw_reasoning_content: str | None = Field(default=None, exclude=True)


class LLMUnavailableError(RuntimeError):
    pass


class Orchestrator:
    def __init__(self, llm: Any, llm_timeout_seconds: float = 60.0) -> None:
        self.llm = llm
        self.llm_timeout_seconds = llm_timeout_seconds

    async def plan_task(
        self,
        goal: str,
        allowed_tools: list[str],
        acceptance_criteria: list[str],
    ) -> TaskPlan:
        risk_policy = self._classify_risk(goal)
        requires_approval = risk_policy in {
            RiskPolicy.HIGH_RISK_WRITE,
            RiskPolicy.DESTRUCTIVE,
        }
        provider_response = await self._provider_response(goal, allowed_tools)
        answer = provider_response.get("answer", provider_response) if isinstance(provider_response, dict) else {}
        provider_steps = answer.get("steps", []) if isinstance(answer, dict) else []
        if not isinstance(provider_steps, list):
            provider_steps = []
        steps = [
            PlanStep(
                id=self._safe_text(step.get("id"), f"step-{index}"),
                title=self._safe_text(step.get("title") or step.get("description"), f"Step {index}"),
                description=self._safe_text(step.get("description") or step.get("title"), goal),
                allowed_tools=self._safe_allowed_tools(step.get("allowed_tools"), allowed_tools),
                command=self._safe_command(step.get("command"), allowed_tools),
                risk_policy=risk_policy,
                requires_approval=requires_approval,
                output_contract=StepContract(required_checks=acceptance_criteria),
            )
            for index, step in enumerate(provider_steps, start=1)
            if isinstance(step, dict)
        ]
        if not steps:
            steps = [
                PlanStep(
                    id="step-1",
                    title="Execute requested task",
                    description=goal,
                    allowed_tools=allowed_tools,
                    command=[],
                    risk_policy=risk_policy,
                    requires_approval=requires_approval,
                    output_contract=StepContract(required_checks=acceptance_criteria),
                )
            ]

        return TaskPlan(
            goal=goal,
            steps=steps,
            output_contract=StepContract(required_checks=acceptance_criteria),
            risk_policy=risk_policy,
            requires_approval=requires_approval,
            execution_contract=self._build_execution_contract(steps, requires_approval),
            research_contract=self._build_research_contract(goal, answer, acceptance_criteria),
            model_thinking_summary_delta=self._model_summary_delta(provider_response),
            model_message=provider_response.get("model_message", {})
            if isinstance(provider_response, dict)
            else {},
            raw_reasoning_content=provider_response.get("raw_reasoning_content")
            if isinstance(provider_response, dict)
            else None,
        )

    def _build_research_contract(
        self,
        goal: str,
        answer: Any,
        acceptance_criteria: list[str],
    ) -> ResearchContract:
        normalized = goal.lower()
        research_terms = (
            "research",
            "analysis",
            "analyze",
            "architecture",
            "исслед",
            "анализ",
            "архитектур",
            "сравни",
        )
        if not any(term in normalized for term in research_terms):
            return ResearchContract(acceptance_criteria=acceptance_criteria)
        defaults = {
            "mode": ResearchMode.RESEARCH,
            "research_questions": [goal],
            "depth": "standard",
            "required_evidence": ["tool_execution", "audit_verdict"],
            "required_artifacts": ["research_report"],
            "output_schema": "research_report",
            "min_tool_executions": 3,
            "acceptance_criteria": acceptance_criteria,
        }
        proposed = answer.get("research_contract") if isinstance(answer, dict) else None
        if isinstance(proposed, dict):
            defaults.update(proposed)
        return ResearchContract.model_validate(defaults)

    def _build_execution_contract(
        self,
        steps: list[PlanStep],
        requires_approval: bool,
    ) -> ExecutionContract:
        tools: list[str] = []
        allowed_paths: list[str] = []
        expected_artifacts: list[str] = []
        write_mode = WriteMode.NONE
        for step in steps:
            for tool in step.allowed_tools:
                if tool not in tools:
                    tools.append(tool)
            expected_artifacts.extend(step.output_contract.required_artifacts)
            command = step.command
            if not command:
                continue
            if command[0] in {"write_file", "apply_patch"}:
                write_mode = WriteMode.CREATE_FILE if command[0] == "write_file" else WriteMode.PATCH
                if len(command) > 1 and command[1] not in allowed_paths:
                    allowed_paths.append(command[1])
            elif command[0] in {"mkdir", "touch"}:
                write_mode = WriteMode.CREATE_FILE
                for path in command[1:]:
                    if not path.startswith("-") and path not in allowed_paths:
                        allowed_paths.append(path)
        return ExecutionContract(
            allowed_tools=tools,
            allowed_paths=allowed_paths,
            write_mode=write_mode,
            expected_artifacts=expected_artifacts,
            output_schema="human_review_packet",
            approval_required=requires_approval or write_mode != WriteMode.NONE,
        )

    async def _provider_response(self, goal: str, allowed_tools: list[str]) -> dict[str, Any]:
        if self.llm is None or not hasattr(self.llm, "complete_json"):
            return {}
        prompt = "\n".join(
            [
                f"Goal: {goal}",
                f"Allowed tools: {', '.join(allowed_tools)}",
                "Return JSON with answer.steps.",
                "Each step must include id, title, description, allowed_tools, and command.",
                "command must be an argv array using only allowed tools.",
                "For write_file use: [\"write_file\", \"relative/path\", \"file content\"].",
                "For apply_patch use: [\"apply_patch\", \"relative/path\", \"old text\", \"new text\"].",
                "Never use absolute paths or '..' in command arguments.",
                "For research or architecture tasks also return answer.research_contract with research_questions, depth, required_evidence, required_artifacts, output_schema, and min_tool_executions.",
            ]
        )
        try:
            response = await self._complete_json_with_hard_timeout(prompt)
        except Exception as exc:
            if isinstance(exc, LLMUnavailableError):
                raise
            raise LLMUnavailableError(str(exc)) from None
        return response if isinstance(response, dict) else {}

    async def _complete_json_with_hard_timeout(self, prompt: str) -> dict[str, Any]:
        request = asyncio.create_task(self.llm.complete_json(prompt, schema_name="plan"))
        done, _ = await asyncio.wait({request}, timeout=self.llm_timeout_seconds)
        if not done:
            request.cancel()
            request.add_done_callback(self._consume_detached_result)
            raise LLMUnavailableError(
                f"orchestrator LLM timed out after {self.llm_timeout_seconds:g} seconds"
            )
        try:
            return request.result()
        except asyncio.CancelledError:
            raise LLMUnavailableError("orchestrator LLM cancelled") from None

    @staticmethod
    def _consume_detached_result(request: asyncio.Task[Any]) -> None:
        if not request.cancelled():
            request.exception()

    def _model_summary_delta(self, provider_response: dict[str, Any]) -> dict[str, Any] | None:
        value = provider_response.get("thinking_summary_delta")
        if isinstance(value, dict):
            return value
        if isinstance(value, str) and value.strip():
            return {
                "stage": "planning",
                "action": "plan_task",
                "summary": value.strip(),
                "observations": [],
                "next_step": "assign_worker",
                "confidence": 0.6,
            }
        return None

    def _safe_allowed_tools(self, provider_tools: Any, allowed_tools: list[str]) -> list[str]:
        if not isinstance(provider_tools, list):
            return list(allowed_tools)
        allowed = set(allowed_tools)
        intersection = [tool for tool in provider_tools if isinstance(tool, str) and tool in allowed]
        return intersection or list(allowed_tools)

    def _safe_text(self, value: Any, fallback: str) -> str:
        if value is None:
            return fallback
        text = str(value).strip()
        return text or fallback

    def _safe_command(self, provider_command: Any, allowed_tools: list[str]) -> list[str]:
        if not isinstance(provider_command, list) or not provider_command:
            return []
        command = [str(part) for part in provider_command]
        tool_name = command[0]
        if tool_name == "git":
            requested_tool = "git"
        elif tool_name in {"echo", "pytest", "rg", "ls", "cat", "sed", "write_file", "apply_patch", "mkdir", "touch"}:
            requested_tool = tool_name
        else:
            requested_tool = "shell"
        if requested_tool not in set(allowed_tools):
            return []
        return command

    def _classify_risk(self, goal: str) -> RiskPolicy:
        normalized = goal.lower()
        destructive_terms = (
            "delete",
            "destroy",
            "drop",
            "wipe",
            "remove production",
            "rm -rf",
            "terminate",
        )
        high_risk_terms = ("deploy", "migrate", "restart", "chmod", "chown", "write")
        if any(term in normalized for term in destructive_terms):
            return RiskPolicy.DESTRUCTIVE
        if any(term in normalized for term in high_risk_terms):
            return RiskPolicy.HIGH_RISK_WRITE
        return RiskPolicy.READ_ONLY
