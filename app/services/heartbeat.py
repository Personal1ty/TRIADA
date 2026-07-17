from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID


class HeartbeatService:
    def __init__(self, *, clock: Any | None = None) -> None:
        self._clock = clock

    def build_payload(
        self,
        *,
        trace: UUID | str,
        agent: str,
        current_stage: str,
        last_completed_action: str | None,
        elapsed_seconds: int,
        created_at: datetime | None = None,
    ) -> dict[str, Any]:
        timestamp = created_at or self._timestamp_for_elapsed(elapsed_seconds)
        return {
            "trace_id": str(trace),
            "agent_id": agent,
            "current_stage": current_stage,
            "last_completed_action": last_completed_action,
            "elapsed_seconds": elapsed_seconds,
            "created_at": timestamp.isoformat(),
        }

    async def emit(
        self,
        emitter: Any | None = None,
        *,
        trace_id: UUID | str,
        task_id: UUID | str,
        agent_id: str,
        current_stage: str,
        last_completed_action: str | None,
        elapsed_seconds: int,
        created_at: datetime | None = None,
    ) -> Any:
        timestamp = created_at or self._timestamp_for_elapsed(elapsed_seconds)
        payload = self.build_payload(
            trace=trace_id,
            agent=agent_id,
            current_stage=current_stage,
            last_completed_action=last_completed_action,
            elapsed_seconds=elapsed_seconds,
            created_at=timestamp,
        )
        if emitter is None:
            return {
                "event_type": "agent_heartbeat",
                "trace_id": str(trace_id),
                "task_id": str(task_id),
                "agent_id": agent_id,
                "payload": payload,
                "created_at": timestamp.isoformat(),
            }
        return await emitter.emit(
            event_type="agent_heartbeat",
            trace_id=trace_id,
            task_id=task_id,
            agent_id=agent_id,
            payload=payload,
            created_at=timestamp,
        )

    def _now(self) -> datetime:
        if self._clock is not None:
            return self._clock.now()
        return datetime.now(UTC)

    def _timestamp_for_elapsed(self, elapsed_seconds: int) -> datetime:
        if self._clock is None or not hasattr(self._clock, "elapsed_seconds"):
            return self._now()
        delta_seconds = int(elapsed_seconds) - int(self._clock.elapsed_seconds)
        return self._clock.now() + timedelta(seconds=delta_seconds)
