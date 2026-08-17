from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class TriadaCheckpoint:
    trace_id: UUID
    event_id: UUID
    sequence: int
    phase: str


class TriadaGraphAdapter:
    """Translate TRIADA checkpoints to a LangGraph-style resume config.

    This boundary deliberately has no LangGraph dependency. A future adapter
    can pass the returned config to a compiled graph while TRIADA remains the
    owner of task identity, audit events, and replay approval.
    """

    def checkpoint(self, *, trace_id: UUID, event_id: UUID, sequence: int, phase: str) -> TriadaCheckpoint:
        return TriadaCheckpoint(trace_id=trace_id, event_id=event_id, sequence=sequence, phase=phase)

    def resume_config(self, checkpoint: TriadaCheckpoint) -> dict[str, dict[str, str]]:
        return {
            "configurable": {
                "thread_id": str(checkpoint.trace_id),
                "checkpoint_id": str(checkpoint.event_id),
            }
        }
