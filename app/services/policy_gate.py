from __future__ import annotations

from pathlib import Path

from app.contracts.execution import ExecutionContract, WriteMode
from app.schemas.enums import RiskPolicy


class PolicyContractError(ValueError):
    pass


class PolicyGate:
    """Bounds an orchestrator proposal by task and system permissions."""

    _WRITE_TOOLS = {"write_file", "apply_patch", "mkdir", "touch"}

    def enforce(
        self,
        proposal: ExecutionContract,
        *,
        task_allowed_tools: list[str],
        risk_policy: RiskPolicy,
    ) -> ExecutionContract:
        task_tools = set(task_allowed_tools)
        effective_tools = [tool for tool in proposal.allowed_tools if tool in task_tools]
        requested_write_tools = set(proposal.allowed_tools) & self._WRITE_TOOLS
        effective_write_tools = set(effective_tools) & self._WRITE_TOOLS
        if requested_write_tools and not effective_write_tools:
            raise PolicyContractError("write capability is outside task permissions")

        self._validate_paths(proposal.allowed_paths)
        self._validate_paths(proposal.forbidden_paths)
        if proposal.write_mode != WriteMode.NONE and not effective_write_tools:
            raise PolicyContractError("write capability is required for a write contract")

        requires_approval = (
            proposal.approval_required
            or proposal.write_mode != WriteMode.NONE
            or risk_policy in {RiskPolicy.HIGH_RISK_WRITE, RiskPolicy.DESTRUCTIVE}
        )
        return proposal.model_copy(
            update={
                "allowed_tools": effective_tools,
                "approval_required": requires_approval,
            }
        )

    def _validate_paths(self, paths: list[str]) -> None:
        for raw_path in paths:
            path = Path(raw_path)
            if path.is_absolute() or ".." in path.parts:
                raise PolicyContractError("contract paths must be relative workspace paths")
