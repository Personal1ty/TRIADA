from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.contracts.swarm import SwarmContract, TaskWeightRule


@dataclass(frozen=True)
class ScalingDecision:
    weight: str
    requested_pairs: int
    selected_worker_ids: list[str]
    selected_auditor_ids: list[str]
    reason: str


def choose_scaling(contract: SwarmContract, *, step_count: int, risk_policy: str) -> ScalingDecision:
    rules = [rule for rule in contract.task_weight_rules if _matches(rule, step_count, risk_policy)]
    rule = max(rules, key=_specificity) if rules else None
    requested_pairs = rule.worker_auditor_pairs if rule is not None else contract.swarm_scaling.default_pairs
    selected_pairs = contract.worker_auditor_pairs[: min(requested_pairs, len(contract.worker_auditor_pairs))]
    weight = rule.weight if rule is not None else "medium"
    return ScalingDecision(
        weight=weight,
        requested_pairs=requested_pairs,
        selected_worker_ids=[pair.worker_id for pair in selected_pairs],
        selected_auditor_ids=[pair.auditor_id for pair in selected_pairs],
        reason=f"{weight} rule selected for {step_count} steps and risk_policy={risk_policy}",
    )


def _matches(rule: TaskWeightRule, step_count: int, risk_policy: str) -> bool:
    if rule.min_steps is not None and step_count < rule.min_steps:
        return False
    if rule.max_steps is not None and step_count > rule.max_steps:
        return False
    if rule.risk_policies and risk_policy not in {policy.value for policy in rule.risk_policies}:
        return False
    return True


def _specificity(rule: TaskWeightRule) -> tuple[int, int]:
    bounds = int(rule.min_steps is not None) + int(rule.max_steps is not None)
    return (int(bool(rule.risk_policies)) + bounds, bounds)
