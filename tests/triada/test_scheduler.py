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
