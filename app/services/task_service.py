from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from app.config import get_settings


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


class InvalidTaskTransition(ValueError):
    pass


class TaskService:
    _ALLOWED_TRANSITIONS: dict[str, set[str]] = {
        "created": {"waiting_approval", "running", "completed", "cancelled"},
        "waiting_approval": {"approved", "running", "cancelled"},
        "approved": {"running", "cancelled"},
        "running": {
            "waiting_approval",
            "corrections_required",
            "retrying",
            "blocked",
            "completed",
            "failed",
            "cancelled",
            "timed_out",
        },
        "corrections_required": {"running", "cancelled"},
        "retrying": {"running", "cancelled", "failed", "completed"},
        "blocked": {"cancelled"},
        "failed": {"cancelled"},
        "completed": set(),
        "cancelled": set(),
        "timed_out": {"cancelled"},
    }

    def __init__(
        self,
        *,
        repository: Any | None = None,
        emitter: Any | None = None,
        execution_engine: Any | None = None,
        execution_timeout_seconds: float | None = None,
    ) -> None:
        self._repository = repository
        self._emitter = emitter
        self._execution_engine = execution_engine
        self._execution_timeout_seconds = (
            execution_timeout_seconds
            if execution_timeout_seconds is not None
            else get_settings().task_execution_timeout_seconds
        )
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
            constraints=deepcopy(constraints) if constraints is not None else {},
            allowed_tools=list(allowed_tools) if allowed_tools is not None else [],
            acceptance_criteria=list(acceptance_criteria) if acceptance_criteria is not None else [],
            timeout_seconds=timeout_seconds,
            retry_limit=retry_limit,
            metadata=deepcopy(metadata) if metadata is not None else {},
        )
        await self._save(task)
        await self._emit(task, "task_created", {"goal": goal, "status": task.status})
        return task

    async def create_replay_task(
        self,
        task_id: UUID | str,
        *,
        from_event_id: UUID | str,
        requested_by: str | None = None,
        reason: str | None = None,
    ) -> TaskRecord:
        source = await self._require_task(task_id)
        replay = await self.create_task(
            goal=source.goal,
            risk=source.risk,
            constraints=source.constraints,
            allowed_tools=source.allowed_tools,
            acceptance_criteria=source.acceptance_criteria,
            timeout_seconds=source.timeout_seconds,
            retry_limit=source.retry_limit,
            metadata={
                "replay": {
                    "parent_task_id": str(source.id),
                    "parent_trace_id": str(source.trace_id),
                    "from_event_id": str(from_event_id),
                    "requested_by": requested_by,
                    "reason": reason,
                }
            },
        )
        waiting = replace(replay, status="waiting_approval", updated_at=datetime.now(UTC))
        await self._emit(
            waiting,
            "replay_waiting_approval",
            {
                "status": "waiting_approval",
                "parent_task_id": str(source.id),
                "parent_trace_id": str(source.trace_id),
                "from_event_id": str(from_event_id),
                "requested_by": requested_by,
                "reason": reason,
            },
        )
        await self._save(waiting)
        return waiting

    async def get_task(self, task_id: UUID | str) -> TaskRecord | None:
        normalized_id = self._normalize_task_id(task_id)
        if self._repository is not None and hasattr(self._repository, "get_task"):
            return await self._repository.get_task(normalized_id)
        task = self._tasks.get(normalized_id)
        return deepcopy(task) if task is not None else None

    async def list_tasks(self, *, limit: int = 20, status: str | None = None) -> list[TaskRecord]:
        if self._repository is not None and hasattr(self._repository, "list_tasks"):
            return await self._repository.list_tasks(limit=limit, status=status)
        tasks = sorted(
            self._tasks.values(),
            key=lambda task: task.created_at,
            reverse=True,
        )
        if status is not None:
            tasks = [task for task in tasks if task.status == status]
        return [deepcopy(task) for task in tasks[:limit]]

    async def cancel_task(self, task_id: UUID | str, *, reason: str | None = None) -> TaskRecord:
        return await self._transition_task(
            task_id,
            status="cancelled",
            event_type="task_cancelled",
            payload={"reason": reason, "status": "cancelled"},
        )

    async def approve_task(self, task_id: UUID | str, *, approved_by: str | None = None) -> TaskRecord:
        task = await self._require_task(task_id)
        self._ensure_transition(task.status, "approved")
        metadata = deepcopy(task.metadata)
        metadata["approval"] = {
            "approved": True,
            "approved_by": approved_by,
            "approved_at": datetime.now(UTC).isoformat(),
        }
        updated = replace(task, status="approved", metadata=metadata, updated_at=datetime.now(UTC))
        await self._emit(updated, "task_approved", {"approved_by": approved_by, "status": "approved"})
        await self._save(updated)
        return updated

    async def resume_task(self, task_id: UUID | str) -> TaskRecord:
        return await self._transition_task(
            task_id,
            status="running",
            event_type="task_resumed",
            payload={"status": "running"},
        )

    async def run_task_once(self, task_id: UUID | str) -> TaskRecord:
        if self._execution_engine is None:
            return await self._transition_task(
                task_id,
                status="completed",
                event_type="task_completed",
                payload={"status": "completed"},
            )

        task = await self._require_task(task_id)
        self._ensure_transition(task.status, "running")
        running = replace(task, status="running", updated_at=datetime.now(UTC))
        await self._emit(running, "task_started", {"status": "running"})
        await self._save(running)
        timeout_seconds = running.timeout_seconds or self._execution_timeout_seconds
        try:
            final_status = await asyncio.wait_for(
                self._execution_engine.run_once(running),
                timeout=timeout_seconds,
            )
        except TimeoutError:
            return await self._transition_task(
                running.id,
                status="timed_out",
                event_type="task_timeout",
                payload={"status": "timed_out", "timeout_seconds": timeout_seconds},
            )
        await self._persist_runtime_metadata(running)
        final_event_type = {
            "blocked": "task_blocked",
            "corrections_required": "task_corrections_required",
            "failed": "task_failed",
            "waiting_approval": "task_waiting_approval",
        }.get(final_status, "task_completed")
        return await self._transition_task(
            running.id,
            status=final_status,
            event_type=final_event_type,
            payload={"status": final_status},
        )

    async def mark_task_completed_without_execution(self, task_id: UUID | str) -> TaskRecord:
        return await self._transition_task(
            task_id,
            status="completed",
            event_type="task_completed",
            payload={"status": "completed"},
        )

    async def _transition_task(
        self,
        task_id: UUID | str,
        *,
        status: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> TaskRecord:
        task = await self._require_task(task_id)
        self._ensure_transition(task.status, status)
        updated = replace(task, status=status, updated_at=datetime.now(UTC))
        await self._emit(updated, event_type, payload)
        await self._save(updated)
        return updated

    async def _require_task(self, task_id: UUID | str) -> TaskRecord:
        task = await self.get_task(task_id)
        if task is None:
            raise KeyError(f"task not found: {task_id}")
        return task

    async def _save(self, task: TaskRecord) -> None:
        if self._repository is not None and hasattr(self._repository, "save_task"):
            await self._repository.save_task(deepcopy(task))
            return
        self._tasks[task.id] = deepcopy(task)

    async def _persist_runtime_metadata(self, runtime_task: TaskRecord) -> None:
        current = await self._require_task(runtime_task.id)
        if current.metadata == runtime_task.metadata:
            return
        await self._save(replace(current, metadata=deepcopy(runtime_task.metadata), updated_at=datetime.now(UTC)))

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

    @classmethod
    def _ensure_transition(cls, current: str, target: str) -> None:
        if target not in cls._ALLOWED_TRANSITIONS.get(current, set()):
            raise InvalidTaskTransition(f"invalid task transition: {current} -> {target}")
