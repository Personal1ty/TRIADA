from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.persistence.models import Base, Task
from app.services.task_service import TaskRecord

_sqlite_task_tables_ready: set[str] = set()


class TaskRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def save_task(self, task: TaskRecord) -> None:
        await self._ensure_sqlite_tables()
        async with self._session_factory() as session:
            existing = await session.get(Task, str(task.id))
            if existing is None:
                session.add(self._to_model(task))
            else:
                existing.trace_id = str(task.trace_id)
                existing.goal = task.goal
                existing.status = task.status
                existing.risk = task.risk
                existing.constraints = task.constraints
                existing.allowed_tools = task.allowed_tools
                existing.acceptance_criteria = task.acceptance_criteria
                existing.timeout_seconds = task.timeout_seconds
                existing.retry_limit = task.retry_limit
                existing.created_at = task.created_at
                existing.updated_at = task.updated_at
                existing.metadata_ = task.metadata
            await session.commit()

    async def get_task(self, task_id: UUID) -> TaskRecord | None:
        await self._ensure_sqlite_tables()
        async with self._session_factory() as session:
            row = await session.get(Task, str(task_id))
        return self._to_record(row) if row is not None else None

    async def list_tasks(self, *, limit: int = 20, status: str | None = None) -> list[TaskRecord]:
        await self._ensure_sqlite_tables()
        statement = select(Task).order_by(Task.created_at.desc(), Task.id.desc()).limit(limit)
        if status is not None:
            statement = statement.where(Task.status == status)
        async with self._session_factory() as session:
            rows = list((await session.scalars(statement)).all())
        return [self._to_record(row) for row in rows]

    def _to_model(self, task: TaskRecord) -> Task:
        return Task(
            id=str(task.id),
            trace_id=str(task.trace_id),
            goal=task.goal,
            status=task.status,
            risk=task.risk,
            constraints=task.constraints,
            allowed_tools=task.allowed_tools,
            acceptance_criteria=task.acceptance_criteria,
            timeout_seconds=task.timeout_seconds,
            retry_limit=task.retry_limit,
            created_at=task.created_at,
            updated_at=task.updated_at,
            metadata_=task.metadata,
        )

    def _to_record(self, task: Task) -> TaskRecord:
        return TaskRecord(
            id=UUID(task.id),
            trace_id=UUID(task.trace_id),
            goal=task.goal,
            status=task.status,
            risk=task.risk,
            constraints=task.constraints,
            allowed_tools=task.allowed_tools,
            acceptance_criteria=task.acceptance_criteria,
            timeout_seconds=task.timeout_seconds,
            retry_limit=task.retry_limit,
            created_at=task.created_at,
            updated_at=task.updated_at,
            metadata=task.metadata_,
        )

    async def _ensure_sqlite_tables(self) -> None:
        bind = self._session_factory.kw.get("bind")
        if bind is None or not bind.url.drivername.startswith("sqlite"):
            return
        engine_key = str(bind.url)
        if engine_key in _sqlite_task_tables_ready:
            return
        async with bind.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        _sqlite_task_tables_ready.add(engine_key)
