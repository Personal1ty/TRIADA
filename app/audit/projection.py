from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID


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


def swarm_graph_from_events(events: list[Any]) -> dict:
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    for event in events:
        if event.event_type != "swarm_route_selected":
            continue
        payload = event.payload if isinstance(event.payload, Mapping) else {}
        source = payload.get("source")
        target = payload.get("target")
        if not source or not target:
            continue
        source_id = str(source)
        target_id = str(target)
        nodes[source_id] = {"id": source_id}
        nodes[target_id] = {"id": target_id}
        edges.append(
            {
                "id": str(event.id),
                "source": source_id,
                "target": target_id,
                "reason": _to_json_safe(payload.get("reason")),
                "input_contract": _to_json_safe(payload.get("input_contract")),
                "output_contract": _to_json_safe(payload.get("output_contract")),
                "sequence": event.sequence,
            }
        )
    return {"nodes": list(nodes.values()), "edges": edges}


def _event_to_public_dict(event: Any) -> dict:
    payload = _to_json_safe(event.payload)
    if event.event_type == "model_reasoning_content_captured" and isinstance(payload, dict):
        payload = dict(payload)
        if "raw_reasoning_content" in payload:
            payload["raw_reasoning_content"] = "[REDACTED]"
    return {
        "id": str(event.id),
        "event_type": event.event_type,
        "trace_id": str(event.trace_id),
        "task_id": str(event.task_id),
        "agent_id": event.agent_id,
        "span_id": _to_json_safe(event.span_id),
        "parent_span_id": _to_json_safe(event.parent_span_id),
        "sequence": event.sequence,
        "payload": payload,
        "created_at": _serialize_datetime(event.created_at),
    }


def _event_to_thinking_delta(event: Any) -> dict:
    payload = dict(event.payload or {})
    return {
        "schema_version": payload.get("schema_version", "1.0"),
        "event_id": str(event.id),
        "trace_id": str(event.trace_id),
        "task_id": str(event.task_id),
        "span_id": _to_json_safe(payload.get("span_id") or event.span_id),
        "parent_span_id": _to_json_safe(payload.get("parent_span_id") or event.parent_span_id),
        "agent_id": payload.get("agent_id") or event.agent_id,
        "agent_role": payload.get("agent_role"),
        "source": payload.get("source"),
        "sequence": event.sequence,
        "stage": payload.get("stage"),
        "action": payload.get("action"),
        "summary": payload.get("summary"),
        "observations": _to_json_safe(payload.get("observations", [])),
        "input_refs": _to_json_safe(payload.get("input_refs", [])),
        "output_refs": _to_json_safe(payload.get("output_refs", [])),
        "next_step": payload.get("next_step"),
        "progress_percent": payload.get("progress_percent"),
        "confidence": payload.get("confidence"),
        "created_at": _serialize_datetime(event.created_at),
        "metadata": _to_json_safe(payload.get("metadata", {})),
    }


def _serialize_datetime(value: datetime) -> str:
    if value.tzinfo is not None:
        value = value.astimezone(UTC)
    return value.isoformat()


def _to_json_safe(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return _serialize_datetime(value)
    if isinstance(value, Mapping):
        return {str(_to_json_safe(key)): _to_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_json_safe(item) for item in value]
    return value
