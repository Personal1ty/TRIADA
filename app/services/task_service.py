from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4


@dataclass
class TaskRecord:
    id: UUID
    trace_id: UUID
    goal: str
    status: str = "created"
    risk: str | None = None
    constraints: dict[str, Any] = field(default_factory=dict)
    allowed_tools: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    timeout_seconds: int | None = None
    retry_limit: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)


class TaskService:
    def __init__(self, *, repository: Any | None = None, emitter: Any | None = None) -> None:
        self._repository = repository
        self._emitter = emitter
        self._tasks: dict[UUID, TaskRecord] = {}

    async def create_task(
        self,
        *,
        goal: str,
        trace_id: UUID | None = None,
        risk: str | None = None,
        constraints: dict[str, Any] | None = None,
        allowed_tools: list[str] | None = None,
        acceptance_criteria: list[str] | None = None,
        timeout_seconds: int | None = None,
        retry_limit: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> TaskRecord:
        task = TaskRecord(
            id=uuid4(),
            trace_id=trace_id or uuid4(),
            goal=goal,
            risk=risk,
            constraints=constraints or {},
            allowed_tools=allowed_tools or [],
            acceptance_criteria=acceptance_criteria or [],
            timeout_seconds=timeout_seconds,
            retry_limit=retry_limit,
            metadata=metadata or {},
        )
        await self._save(task)
        await self._emit(task, "task_created", {"goal": goal, "status": task.status})
        return task

    async def get_task(self, task_id: UUID | str) -> TaskRecord | None:
        normalized_id = self._normalize_task_id(task_id)
        if self._repository is not None and hasattr(self._repository, "get_task"):
            return await self._repository.get_task(normalized_id)
        return self._tasks.get(normalized_id)

    async def cancel_task(self, task_id: UUID | str, *, reason: str | None = None) -> TaskRecord:
        task = await self._require_task(task_id)
        task.status = "cancelled"
        task.updated_at = datetime.now(UTC)
        await self._save(task)
        await self._emit(task, "task_cancelled", {"reason": reason, "status": task.status})
        return task

    async def approve_task(self, task_id: UUID | str, *, approved_by: str | None = None) -> TaskRecord:
        task = await self._require_task(task_id)
        task.status = "approved"
        task.updated_at = datetime.now(UTC)
        await self._save(task)
        await self._emit(task, "task_approved", {"approved_by": approved_by, "status": task.status})
        return task

    async def resume_task(self, task_id: UUID | str) -> TaskRecord:
        task = await self._require_task(task_id)
        task.status = "running"
        task.updated_at = datetime.now(UTC)
        await self._save(task)
        await self._emit(task, "task_resumed", {"status": task.status})
        return task

    async def run_task_once(self, task_id: UUID | str) -> TaskRecord:
        task = await self._require_task(task_id)
        task.status = "completed"
        task.updated_at = datetime.now(UTC)
        await self._save(task)
        await self._emit(task, "task_completed", {"status": task.status})
        return task

    async def _require_task(self, task_id: UUID | str) -> TaskRecord:
        task = await self.get_task(task_id)
        if task is None:
            raise KeyError(f"task not found: {task_id}")
        return task

    async def _save(self, task: TaskRecord) -> None:
        if self._repository is not None and hasattr(self._repository, "save_task"):
            await self._repository.save_task(task)
            return
        self._tasks[task.id] = task

    async def _emit(self, task: TaskRecord, event_type: str, payload: dict[str, Any]) -> None:
        if self._emitter is None:
            return
        await self._emitter.emit(
            event_type=event_type,
            trace_id=task.trace_id,
            task_id=task.id,
            agent_id="task_service",
            payload=payload,
        )

    @staticmethod
    def _normalize_task_id(task_id: UUID | str) -> UUID:
        if isinstance(task_id, UUID):
            return task_id
        return UUID(str(task_id))
