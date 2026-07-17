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
        provider_steps = await self._provider_steps(goal, allowed_tools)
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
        )

    async def _provider_steps(self, goal: str, allowed_tools: list[str]) -> list[dict[str, Any]]:
        if self.llm is None or not hasattr(self.llm, "complete_json"):
            return []
        prompt = f"Goal: {goal}\nAllowed tools: {', '.join(allowed_tools)}"
        try:
            response = await self.llm.complete_json(prompt, schema_name="plan")
        except Exception:
            return []
        answer = response.get("answer", response) if isinstance(response, dict) else {}
        steps = answer.get("steps", []) if isinstance(answer, dict) else []
        return steps if isinstance(steps, list) else []

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
