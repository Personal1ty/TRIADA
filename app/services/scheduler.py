from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from typing import TypeVar


Item = TypeVar("Item")
Result = TypeVar("Result")


class BoundedStepScheduler:
    """Run independent work with global and per-worker concurrency bounds."""

    def __init__(self, *, max_concurrency: int, worker_limits: dict[str, int] | None = None) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        self._global_limit = asyncio.Semaphore(max_concurrency)
        self._worker_limits = {}
        for worker_id, limit in (worker_limits or {}).items():
            if limit < 1:
                raise ValueError("worker limits must be at least 1")
            self._worker_limits[worker_id] = asyncio.Semaphore(limit)

    async def run(
        self,
        items: Iterable[Item],
        *,
        worker_key: Callable[[Item], str],
        run: Callable[[Item], Awaitable[Result]],
    ) -> list[Result]:
        ordered_items = list(items)
        results: list[Result | None] = [None] * len(ordered_items)

        async def execute(index: int, item: Item) -> None:
            worker_id = worker_key(item)
            worker_limit = self._worker_limits.get(worker_id)
            async with self._global_limit:
                if worker_limit is None:
                    results[index] = await run(item)
                else:
                    async with worker_limit:
                        results[index] = await run(item)

        await asyncio.gather(*(execute(index, item) for index, item in enumerate(ordered_items)))
        return [result for result in results]
