from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.enums import RiskPolicy


class StepContract(BaseModel):
    required_checks: list[str] = Field(default_factory=list)
    required_artifacts: list[str] = Field(default_factory=list)


class PlanStep(BaseModel):
    id: str
    title: str
    description: str
    allowed_tools: list[str] = Field(default_factory=list)
    risk_policy: RiskPolicy = RiskPolicy.READ_ONLY
    requires_approval: bool = False
    output_contract: StepContract = Field(default_factory=StepContract)


class TaskPlan(BaseModel):
    goal: str
    steps: list[PlanStep] = Field(default_factory=list)
    output_contract: StepContract = Field(default_factory=StepContract)
    risk_policy: RiskPolicy = RiskPolicy.READ_ONLY
    requires_approval: bool = False
    model_thinking_summary_delta: dict[str, Any] | None = None
    model_message: dict[str, Any] = Field(default_factory=dict)
    raw_reasoning_content: str | None = Field(default=None, exclude=True)


class LLMUnavailableError(RuntimeError):
    pass


class Orchestrator:
    def __init__(self, llm: Any) -> None:
        self.llm = llm

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
                id=step.get("id") or f"step-{index}",
                title=step.get("title") or step.get("description") or f"Step {index}",
                description=step.get("description") or step.get("title") or goal,
                allowed_tools=self._safe_allowed_tools(step.get("allowed_tools"), allowed_tools),
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
            model_thinking_summary_delta=provider_response.get("thinking_summary_delta")
            if isinstance(provider_response, dict)
            else None,
            model_message=provider_response.get("model_message", {})
            if isinstance(provider_response, dict)
            else {},
            raw_reasoning_content=provider_response.get("raw_reasoning_content")
            if isinstance(provider_response, dict)
            else None,
        )

    async def _provider_response(self, goal: str, allowed_tools: list[str]) -> dict[str, Any]:
        if self.llm is None or not hasattr(self.llm, "complete_json"):
            return {}
        prompt = f"Goal: {goal}\nAllowed tools: {', '.join(allowed_tools)}"
        try:
            response = await self.llm.complete_json(prompt, schema_name="plan")
        except Exception as exc:
            raise LLMUnavailableError(str(exc)) from None
        return response if isinstance(response, dict) else {}

    def _safe_allowed_tools(self, provider_tools: Any, allowed_tools: list[str]) -> list[str]:
        if not isinstance(provider_tools, list):
            return list(allowed_tools)
        allowed = set(allowed_tools)
        intersection = [tool for tool in provider_tools if isinstance(tool, str) and tool in allowed]
        return intersection or list(allowed_tools)

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
