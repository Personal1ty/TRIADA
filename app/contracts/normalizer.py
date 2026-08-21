from __future__ import annotations

from typing import Any

from app.contracts.research import ResearchContract, ResearchMode


class ContractNormalizer:
    """Convert an LLM contract draft into a safe canonical semantic contract."""

    _RESEARCH_FIELDS = {
        "mode",
        "research_questions",
        "depth",
        "required_evidence",
        "required_artifacts",
        "output_schema",
        "min_tool_executions",
        "acceptance_criteria",
    }

    def research(
        self,
        draft: Any,
        *,
        goal: str,
        acceptance_criteria: list[str],
    ) -> ResearchContract:
        defaults: dict[str, Any] = {
            "mode": ResearchMode.RESEARCH,
            "research_questions": [goal],
            "depth": "standard",
            "required_evidence": ["tool_execution", "audit_verdict"],
            "required_artifacts": ["research_report"],
            "output_schema": "research_report",
            "min_tool_executions": 3,
            "acceptance_criteria": acceptance_criteria,
        }
        if isinstance(draft, dict):
            defaults.update(
                {
                    key: value
                    for key, value in draft.items()
                    if key in self._RESEARCH_FIELDS
                }
            )

        mode = defaults.get("mode")
        defaults["mode"] = mode if mode in {ResearchMode.NONE, ResearchMode.RESEARCH, "none", "research"} else ResearchMode.RESEARCH
        if defaults["mode"] == ResearchMode.NONE:
            defaults.update(
                {
                    "research_questions": [],
                    "required_evidence": [],
                    "required_artifacts": [],
                    "min_tool_executions": 0,
                }
            )
        else:
            defaults["research_questions"] = self._string_list(defaults.get("research_questions"), [goal])
            defaults["required_evidence"] = self._string_list(
                defaults.get("required_evidence"), ["tool_execution", "audit_verdict"]
            )
            defaults["required_artifacts"] = self._string_list(
                defaults.get("required_artifacts"), ["research_report"]
            )
            defaults["min_tool_executions"] = self._nonnegative_int(
                defaults.get("min_tool_executions"), 3
            )
        defaults["depth"] = self._string_value(defaults.get("depth"), "standard")
        defaults["output_schema"] = self._string_value(defaults.get("output_schema"), "research_report")
        defaults["acceptance_criteria"] = self._string_list(
            defaults.get("acceptance_criteria"), acceptance_criteria
        )
        return ResearchContract.model_validate(defaults)

    def _string_list(self, value: Any, fallback: list[str]) -> list[str]:
        if isinstance(value, str):
            return [value] if value.strip() else list(fallback)
        if isinstance(value, list):
            items = [str(item).strip() for item in value if item is not None and str(item).strip()]
            return items or list(fallback)
        return list(fallback)

    def _string_value(self, value: Any, fallback: str) -> str:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
        return fallback

    def _nonnegative_int(self, value: Any, fallback: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return fallback
        return parsed if parsed >= 0 else fallback
