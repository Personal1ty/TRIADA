from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID


class _TraceSubscription:
    def __init__(self, bus: InMemoryEventBus, trace_id: str, queue: asyncio.Queue[Any]) -> None:
        self._bus = bus
        self._trace_id = trace_id
        self._queue = queue
        self._closed = False

    def __aiter__(self) -> "_TraceSubscription":
        return self

    async def __anext__(self) -> Any:
        if self._closed:
            raise StopAsyncIteration
        try:
            return await self._queue.get()
        except asyncio.CancelledError:
            await self.aclose()
            raise

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._bus._remove_listener(self._trace_id, self._queue)


class InMemoryEventBus:
    def __init__(self, *, listener_queue_size: int = 100) -> None:
        self._listener_queue_size = listener_queue_size
        self._listeners: dict[str, set[asyncio.Queue[Any]]] = defaultdict(set)
        self._published: list[Any] = []
        self._lock = asyncio.Lock()

    async def publish(self, event: Any) -> None:
        trace_id = str(event.trace_id)
        async with self._lock:
            self._published.append(event)
            listeners = tuple(self._listeners.get(trace_id, ()))

        for queue in listeners:
            await queue.put(event)

    def subscribe(self, trace_id: UUID | str) -> AsyncIterator[Any]:
        trace_id_str = str(trace_id)
        queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=self._listener_queue_size)
        self._listeners[trace_id_str].add(queue)
        return _TraceSubscription(self, trace_id_str, queue)

    async def drain(self) -> list[Any]:
        async with self._lock:
            events = list(self._published)
            self._published.clear()
        return events

    def listener_count(self, trace_id: UUID | str) -> int:
        return len(self._listeners.get(str(trace_id), ()))

    async def _remove_listener(self, trace_id: str, queue: asyncio.Queue[Any]) -> None:
        listeners = self._listeners.get(trace_id)
        if listeners is None:
            return
        listeners.discard(queue)
        if not listeners:
            self._listeners.pop(trace_id, None)
