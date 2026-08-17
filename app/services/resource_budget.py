from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ResourceBudget:
    max_parallel_branches: int = 1
    max_retries: int = 0
    max_tokens: int = 0

    def __post_init__(self) -> None:
        for name in ("max_parallel_branches", "max_retries", "max_tokens"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")


@dataclass(frozen=True, slots=True)
class ResourceUsage:
    active_branches: int = 0
    retries: int = 0
    tokens_used: int = 0

    def __post_init__(self) -> None:
        for name in ("active_branches", "retries", "tokens_used"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")


@dataclass(frozen=True, slots=True)
class AllocationDecision:
    admitted: bool
    reason: str


def allocate_work(budget: ResourceBudget, usage: ResourceUsage) -> AllocationDecision:
    if usage.active_branches >= budget.max_parallel_branches:
        return AllocationDecision(False, "parallel_branches_exhausted")
    if usage.retries >= budget.max_retries:
        return AllocationDecision(False, "retries_exhausted")
    if budget.max_tokens > 0 and usage.tokens_used >= budget.max_tokens:
        return AllocationDecision(False, "tokens_exhausted")
    return AllocationDecision(True, "within_budget")
