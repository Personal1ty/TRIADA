from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any


def event_to_sse(event: Any) -> dict[str, str]:
    return {
        "id": str(event.id),
        "event": str(event.event_type),
        "data": json.dumps(_event_to_public_dict(event), sort_keys=True),
    }


def events_to_public_response(events: list[Any]) -> list[dict]:
    return [_event_to_public_dict(event) for event in events]


def thinking_deltas_from_events(events: list[Any]) -> list[dict]:
    return [_event_to_thinking_delta(event) for event in events if event.event_type == "thinking_summary_delta"]


def _event_to_public_dict(event: Any) -> dict:
    return {
        "id": str(event.id),
        "event_type": event.event_type,
        "trace_id": str(event.trace_id),
        "task_id": str(event.task_id),
        "agent_id": event.agent_id,
        "span_id": event.span_id,
        "parent_span_id": event.parent_span_id,
        "sequence": event.sequence,
        "payload": event.payload,
        "created_at": _serialize_datetime(event.created_at),
    }


def _event_to_thinking_delta(event: Any) -> dict:
    payload = dict(event.payload or {})
    return {
        "schema_version": payload.get("schema_version", "1.0"),
        "event_id": str(event.id),
        "trace_id": str(event.trace_id),
        "task_id": str(event.task_id),
        "span_id": payload.get("span_id") or event.span_id,
        "parent_span_id": payload.get("parent_span_id") or event.parent_span_id,
        "agent_id": payload.get("agent_id") or event.agent_id,
        "agent_role": payload.get("agent_role"),
        "source": payload.get("source"),
        "sequence": event.sequence,
        "stage": payload.get("stage"),
        "action": payload.get("action"),
        "summary": payload.get("summary"),
        "observations": payload.get("observations", []),
        "input_refs": payload.get("input_refs", []),
        "output_refs": payload.get("output_refs", []),
        "next_step": payload.get("next_step"),
        "progress_percent": payload.get("progress_percent"),
        "confidence": payload.get("confidence"),
        "created_at": _serialize_datetime(event.created_at),
        "metadata": payload.get("metadata", {}),
    }


def _serialize_datetime(value: datetime) -> str:
    if value.tzinfo is not None:
        value = value.astimezone(UTC)
    return value.isoformat()
