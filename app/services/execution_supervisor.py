from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from app.schemas.enums import AgentRole, DeltaSource
from app.services.heartbeat import HeartbeatService


class FakeClock:
    def __init__(self, *, start: int = 0) -> None:
        self._start = datetime(1970, 1, 1, tzinfo=UTC)
        self._elapsed_seconds = int(start)

    @property
    def elapsed_seconds(self) -> int:
        return self._elapsed_seconds

    def now(self) -> datetime:
        return self._start + timedelta(seconds=self._elapsed_seconds)

    def advance_to(self, elapsed_seconds: int) -> None:
        if elapsed_seconds < self._elapsed_seconds:
            raise ValueError("fake clock cannot move backwards")
        self._elapsed_seconds = int(elapsed_seconds)

    def advance(self, seconds: int) -> None:
        if seconds < 0:
            raise ValueError("fake clock cannot move backwards")
        self._elapsed_seconds += int(seconds)


@dataclass(frozen=True)
class LongTaskSimulationResult:
    status: str
    events: list[dict[str, Any]] = field(default_factory=list)
    elapsed_seconds: int = 0


class LongTaskSimulator:
    def __init__(
        self,
        *,
        clock: FakeClock,
        heartbeat_seconds: int,
        checkpoint_seconds: int,
        trace_id: UUID | None = None,
        task_id: UUID | None = None,
        agent_id: str = "worker-1",
    ) -> None:
        if heartbeat_seconds <= 0:
            raise ValueError("heartbeat_seconds must be positive")
        if checkpoint_seconds <= 0:
            raise ValueError("checkpoint_seconds must be positive")

        self._clock = clock
        self._heartbeat_seconds = heartbeat_seconds
        self._checkpoint_seconds = checkpoint_seconds
        self._trace_id = trace_id or uuid4()
        self._task_id = task_id or uuid4()
        self._span_id = uuid4()
        self._agent_id = agent_id
        self._heartbeat = HeartbeatService(clock=clock)

    async def run_virtual(self, *, duration_seconds: int, timeout_seconds: int) -> LongTaskSimulationResult:
        if duration_seconds < 0:
            raise ValueError("duration_seconds must be non-negative")
        if timeout_seconds < 0:
            raise ValueError("timeout_seconds must be non-negative")

        events: list[dict[str, Any]] = []
        finish_at = min(duration_seconds, timeout_seconds)
        next_heartbeat = self._next_interval(self._clock.elapsed_seconds, self._heartbeat_seconds)
        next_checkpoint = self._next_interval(self._clock.elapsed_seconds, self._checkpoint_seconds)

        while True:
            next_tick = min(next_heartbeat, next_checkpoint, finish_at)
            self._clock.advance_to(next_tick)

            if next_tick == next_heartbeat:
                events.append(self._heartbeat_event())
                next_heartbeat += self._heartbeat_seconds

            if next_tick == next_checkpoint:
                events.append(self._thinking_delta_event())
                next_checkpoint += self._checkpoint_seconds

            if next_tick == finish_at:
                break

        if timeout_seconds < duration_seconds:
            events.append(self._event("task_timeout", {"elapsed_seconds": self._clock.elapsed_seconds}))
            events.append(self._event("task_cancelled", {"elapsed_seconds": self._clock.elapsed_seconds}))
            status = "timed_out"
        else:
            events.append(self._event("task_completed", {"elapsed_seconds": self._clock.elapsed_seconds}))
            status = "completed"

        return LongTaskSimulationResult(
            status=status,
            events=events,
            elapsed_seconds=self._clock.elapsed_seconds,
        )

    def _heartbeat_event(self) -> dict[str, Any]:
        payload = self._heartbeat.build_payload(
            trace=self._trace_id,
            agent=self._agent_id,
            current_stage="running",
            last_completed_action="virtual_step",
            elapsed_seconds=self._clock.elapsed_seconds,
            created_at=self._clock.now(),
        )
        return self._event("agent_heartbeat", payload)

    def _thinking_delta_event(self) -> dict[str, Any]:
        elapsed = self._clock.elapsed_seconds
        payload = {
            "schema_version": "1.0",
            "agent_id": self._agent_id,
            "agent_role": AgentRole.WORKER.value,
            "source": DeltaSource.RUNTIME.value,
            "span_id": str(self._span_id),
            "elapsed_seconds": elapsed,
            "stage": "running",
            "action": "checkpoint",
            "summary": f"Task is still running after {elapsed} seconds.",
            "observations": [],
            "input_refs": [],
            "output_refs": [],
            "created_at": self._clock.now().isoformat(),
            "metadata": {"elapsed_seconds": elapsed},
        }
        return self._event("thinking_summary_delta", payload)

    def _event(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "event_type": event_type,
            "trace_id": str(self._trace_id),
            "task_id": str(self._task_id),
            "agent_id": self._agent_id,
            "payload": payload,
            "created_at": self._clock.now().isoformat(),
        }

    @staticmethod
    def _next_interval(elapsed_seconds: int, interval_seconds: int) -> int:
        return ((elapsed_seconds // interval_seconds) + 1) * interval_seconds
