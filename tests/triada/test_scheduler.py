import asyncio

import pytest

from app.services.scheduler import BoundedStepScheduler


@pytest.mark.asyncio
async def test_scheduler_respects_global_parallelism():
    scheduler = BoundedStepScheduler(max_concurrency=2)
    active = 0
    peak = 0

    async def run(item: int) -> int:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return item * 2

    result = await scheduler.run([1, 2, 3, 4], worker_key=lambda _: "shared", run=run)

    assert result == [2, 4, 6, 8]
    assert peak == 2


@pytest.mark.asyncio
async def test_scheduler_respects_each_worker_limit():
    scheduler = BoundedStepScheduler(max_concurrency=4, worker_limits={"worker-1": 1, "worker-2": 2})
    active_by_worker = {"worker-1": 0, "worker-2": 0}
    peak_by_worker = {"worker-1": 0, "worker-2": 0}
    items = [("worker-1", 1), ("worker-1", 2), ("worker-2", 3), ("worker-2", 4), ("worker-2", 5)]

    async def run(item: tuple[str, int]) -> tuple[str, int]:
        worker_id, value = item
        active_by_worker[worker_id] += 1
        peak_by_worker[worker_id] = max(peak_by_worker[worker_id], active_by_worker[worker_id])
        await asyncio.sleep(0.01)
        active_by_worker[worker_id] -= 1
        return item

    result = await scheduler.run(items, worker_key=lambda item: item[0], run=run)

    assert result == items
    assert peak_by_worker == {"worker-1": 1, "worker-2": 2}


@pytest.mark.asyncio
async def test_scheduler_rejects_invalid_capacity():
    with pytest.raises(ValueError, match="max_concurrency"):
        BoundedStepScheduler(max_concurrency=0)


def test_execution_plan_batches_put_verification_after_writes():
    from app.agents.orchestrator import PlanStep
    from app.services.execution_engine import ExecutionEngine

    steps = [
        PlanStep(
            id="write",
            title="Create module",
            description="create",
            allowed_tools=["write_file"],
            command=["write_file", "triada-dev-tests/module.py", "value = 1\n"],
        ),
        PlanStep(
            id="test",
            title="Run tests",
            description="test",
            allowed_tools=["pytest"],
            command=["pytest", "triada-dev-tests/test_module.py"],
        ),
    ]

    batches = ExecutionEngine.ordered_step_batches(steps)

    assert [[step.id for step in batch] for batch in batches] == [["write"], ["test"]]


def test_execution_plan_rejects_dependency_cycle():
    from app.agents.orchestrator import PlanStep
    from app.services.execution_engine import ExecutionEngine

    steps = [
        PlanStep(id="a", title="A", description="A", depends_on=["b"]),
        PlanStep(id="b", title="B", description="B", depends_on=["a"]),
    ]

    with pytest.raises(ValueError, match="dependency cycle"):
        ExecutionEngine.ordered_step_batches(steps)
