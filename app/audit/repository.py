from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import hashlib
import json
from typing import Any
from uuid import UUID, uuid4
from weakref import WeakValueDictionary

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.persistence.models import AuditEvent, Base


_sqlite_table_locks: dict[str, asyncio.Lock] = {}
_sqlite_tables_ready: set[str] = set()
_trace_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()
_lock_registry_guard = asyncio.Lock()


def _json_default(value: object) -> str:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return _canonical_datetime(value)
    return str(value)


def _canonical_datetime(value: datetime) -> str:
    if value.tzinfo is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return value.isoformat()


def canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=_json_default)


def compute_event_hash(event_dict: dict[str, object], previous_hash: str) -> str:
    canonical_event_json = canonical_json(event_dict)
    return hashlib.sha256(f"{canonical_event_json}{previous_hash}".encode("utf-8")).hexdigest()


class AuditEventRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def _ensure_sqlite_tables(self) -> None:
        bind = self._session_factory.kw.get("bind")
        if bind is None or not bind.url.drivername.startswith("sqlite"):
            return
        engine_key = str(bind.url)
        if engine_key in _sqlite_tables_ready:
            return
        table_lock = await _get_lock(_sqlite_table_locks, engine_key)
        async with table_lock:
            if engine_key in _sqlite_tables_ready:
                return
            async with bind.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            _sqlite_tables_ready.add(engine_key)

    async def append_event(
        self,
        *,
        event_type: str,
        trace_id: UUID,
        task_id: UUID,
        agent_id: str | None,
        payload: dict[str, Any],
        id: UUID | None = None,
        span_id: UUID | None = None,
        parent_span_id: UUID | None = None,
        sequence: int | None = None,
        created_at: datetime | None = None,
    ) -> AuditEvent:
        await self._ensure_sqlite_tables()

        event_id = str(id or uuid4())
        trace_id_str = str(trace_id)
        task_id_str = str(task_id)
        created_at = created_at or datetime.now(UTC)
        trace_lock = await _get_lock(_trace_locks, trace_id_str)

        async with trace_lock:
            return await self._append_event_locked(
                event_id=event_id,
                event_type=event_type,
                trace_id=trace_id_str,
                task_id=task_id_str,
                agent_id=agent_id,
                payload=payload,
                span_id=str(span_id) if span_id is not None else None,
                parent_span_id=str(parent_span_id) if parent_span_id is not None else None,
                sequence=sequence,
                created_at=created_at,
            )

    async def _append_event_locked(
        self,
        *,
        event_id: str,
        event_type: str,
        trace_id: str,
        task_id: str,
        agent_id: str | None,
        payload: dict[str, Any],
        span_id: str | None,
        parent_span_id: str | None,
        sequence: int | None,
        created_at: datetime,
    ) -> AuditEvent:
        async with self._session_factory() as session:
            if await session.get(AuditEvent, event_id) is not None:
                raise ValueError(f"duplicate event id {event_id}")

            last_event = await self._last_event(session, trace_id)
            if sequence is None:
                max_sequence = await session.scalar(
                    select(func.max(AuditEvent.sequence)).where(AuditEvent.trace_id == trace_id)
                )
                sequence = int(max_sequence or 0) + 1

            previous_hash = last_event.event_hash if last_event is not None else ""
            event_dict: dict[str, object] = {
                "id": event_id,
                "event_type": event_type,
                "trace_id": trace_id,
                "task_id": task_id,
                "agent_id": agent_id,
                "span_id": span_id,
                "parent_span_id": parent_span_id,
                "sequence": sequence,
                "payload": payload,
                "created_at": _canonical_datetime(created_at),
            }
            event_hash = compute_event_hash(event_dict, previous_hash)

            event = AuditEvent(
                id=event_id,
                event_type=event_type,
                trace_id=trace_id,
                task_id=task_id,
                agent_id=agent_id,
                span_id=span_id,
                parent_span_id=parent_span_id,
                sequence=sequence,
                payload=payload,
                previous_hash=previous_hash,
                event_hash=event_hash,
                created_at=created_at,
            )
            session.add(event)
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise _integrity_error_for_event(exc, event_id, trace_id, sequence) from exc
            await session.refresh(event)
            return event

    async def list_events(self, trace_id: UUID, after_event_id: UUID | None = None) -> list[AuditEvent]:
        await self._ensure_sqlite_tables()
        trace_id_str = str(trace_id)
        async with self._session_factory() as session:
            statement = (
                select(AuditEvent)
                .where(AuditEvent.trace_id == trace_id_str)
                .order_by(AuditEvent.sequence, AuditEvent.created_at, AuditEvent.id)
            )
            events = list((await session.scalars(statement)).all())

        if after_event_id is None:
            return events

        after_id = str(after_event_id)
        for index, event in enumerate(events):
            if event.id == after_id:
                return events[index + 1 :]
        return events

    async def list_events_by_type(self, event_type: str, *, limit: int = 500) -> list[AuditEvent]:
        await self._ensure_sqlite_tables()
        async with self._session_factory() as session:
            statement = (
                select(AuditEvent)
                .where(AuditEvent.event_type == event_type)
                .order_by(AuditEvent.created_at.desc(), AuditEvent.sequence.desc())
                .limit(limit)
            )
            return list((await session.scalars(statement)).all())

    async def verify_trace(self, trace_id: UUID) -> bool:
        events = await self.list_events(trace_id)
        previous_hash = ""
        seen_ids: set[str] = set()
        expected_sequence = 1
        for event in events:
            if event.id in seen_ids:
                return False
            seen_ids.add(event.id)
            if event.sequence != expected_sequence:
                return False
            if event.previous_hash != previous_hash:
                return False
            event_dict: dict[str, object] = {
                "id": event.id,
                "event_type": event.event_type,
                "trace_id": event.trace_id,
                "task_id": event.task_id,
                "agent_id": event.agent_id,
                "span_id": event.span_id,
                "parent_span_id": event.parent_span_id,
                "sequence": event.sequence,
                "payload": event.payload,
                "created_at": _canonical_datetime(event.created_at),
            }
            if compute_event_hash(event_dict, event.previous_hash) != event.event_hash:
                return False
            previous_hash = event.event_hash
            expected_sequence += 1
        return True

    async def _last_event(self, session: AsyncSession, trace_id: str) -> AuditEvent | None:
        statement = (
            select(AuditEvent)
            .where(AuditEvent.trace_id == trace_id)
            .order_by(AuditEvent.sequence.desc(), AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .limit(1)
        )
        return await session.scalar(statement)


async def _get_lock(registry: dict[str, asyncio.Lock] | WeakValueDictionary[str, asyncio.Lock], key: str) -> asyncio.Lock:
    async with _lock_registry_guard:
        lock = registry.get(key)
        if lock is None:
            lock = asyncio.Lock()
            registry[key] = lock
        return lock


def _integrity_error_for_event(exc: IntegrityError, event_id: str, trace_id: str, sequence: int) -> ValueError:
    message = str(exc.orig).lower()
    if "audit_events.trace_id" in message and "audit_events.sequence" in message:
        return ValueError(f"duplicate event sequence {sequence} for trace {trace_id}")
    return ValueError(f"duplicate event id {event_id}")
