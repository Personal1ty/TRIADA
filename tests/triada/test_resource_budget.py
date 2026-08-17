import pytest

from app.services.resource_budget import ResourceBudget, ResourceUsage, allocate_work
from app.schemas.tasks import CreateTaskRequest


def test_allocate_admits_work_inside_budget():
    decision = allocate_work(
        ResourceBudget(max_parallel_branches=2, max_retries=1, max_tokens=1000),
        ResourceUsage(active_branches=1, retries=0, tokens_used=200),
    )

    assert decision.admitted is True
    assert decision.reason == "within_budget"


def test_allocate_rejects_parallel_branch_overage():
    decision = allocate_work(
        ResourceBudget(max_parallel_branches=2, max_retries=1, max_tokens=1000),
        ResourceUsage(active_branches=2, retries=0, tokens_used=200),
    )

    assert decision.admitted is False
    assert decision.reason == "parallel_branches_exhausted"


def test_allocate_rejects_retry_and_token_overage_in_stable_order():
    budget = ResourceBudget(max_parallel_branches=2, max_retries=1, max_tokens=1000)

    assert allocate_work(budget, ResourceUsage(active_branches=0, retries=1, tokens_used=0)).reason == "retries_exhausted"
    assert allocate_work(budget, ResourceUsage(active_branches=0, retries=0, tokens_used=1000)).reason == "tokens_exhausted"


def test_budget_rejects_negative_limits():
    with pytest.raises(ValueError, match="max_parallel_branches"):
        ResourceBudget(max_parallel_branches=-1)

    with pytest.raises(ValueError, match="max_retries"):
        ResourceBudget(max_retries=-1)

    with pytest.raises(ValueError, match="max_tokens"):
        ResourceBudget(max_tokens=-1)


def test_task_request_accepts_bounded_resource_budget():
    request = CreateTaskRequest(
        goal="Research a bounded question",
        resource_budget={"max_parallel_branches": 3, "max_retries": 2, "max_tokens": 4000},
    )

    assert request.resource_budget.max_parallel_branches == 3
    assert request.resource_budget.max_retries == 2
    assert request.resource_budget.max_tokens == 4000


def test_task_request_rejects_negative_resource_budget():
    with pytest.raises(ValueError, match="max_tokens"):
        CreateTaskRequest(goal="Research", resource_budget={"max_tokens": -1})
