from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from app.audit.redaction import redact_payload


class AuditEmitter:
    def __init__(self, repository: Any, bus: Any) -> None:
        self._repository = repository
        self._bus = bus

    async def emit(
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
    ) -> Any:
        redacted_payload = redact_payload(payload)
        if not isinstance(redacted_payload, dict):
            raise TypeError("audit event payload must redact to a dict")

        event = await self._repository.append_event(
            id=id,
            event_type=event_type,
            trace_id=trace_id,
            task_id=task_id,
            agent_id=agent_id,
            payload=redacted_payload,
            span_id=span_id,
            parent_span_id=parent_span_id,
            sequence=sequence,
            created_at=created_at,
        )
        await self._bus.publish(event)
        return event
