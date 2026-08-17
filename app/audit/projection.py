from __future__ import annotations

import json
import re
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
        source = payload.get("source_agent_id") or payload.get("source")
        target = payload.get("target_agent_id") or payload.get("target")
        if not source or not target:
            continue
        source_id = str(source)
        target_id = str(target)
        nodes.setdefault(source_id, _graph_node(source_id, endpoint_role=str(payload.get("source") or source_id)))
        nodes.setdefault(target_id, _graph_node(target_id, endpoint_role=str(payload.get("target") or target_id)))
        nodes[source_id]["outgoing_count"] += 1
        nodes[source_id]["last_sequence"] = event.sequence
        nodes[target_id]["incoming_count"] += 1
        nodes[target_id]["last_sequence"] = event.sequence
        if nodes[source_id]["first_sequence"] is None:
            nodes[source_id]["first_sequence"] = event.sequence
        if nodes[target_id]["first_sequence"] is None:
            nodes[target_id]["first_sequence"] = event.sequence
        reason = _to_json_safe(payload.get("reason"))
        edges.append(
            {
                "id": str(event.id),
                "source": source_id,
                "target": target_id,
                "source_endpoint": _to_json_safe(payload.get("source")),
                "target_endpoint": _to_json_safe(payload.get("target")),
                "reason": reason,
                "label": f"{event.sequence}. {reason}",
                "status": "selected",
                "input_contract": _to_json_safe(payload.get("input_contract")),
                "output_contract": _to_json_safe(payload.get("output_contract")),
                "sequence": event.sequence,
            }
        )
    ordered_nodes = sorted(nodes.values(), key=lambda node: (node["first_sequence"] or 0, node["id"]))
    ordered_edges = sorted(edges, key=lambda edge: edge["sequence"])
    return {
        "summary": {
            "node_count": len(ordered_nodes),
            "edge_count": len(ordered_edges),
            "route_reasons": [edge["reason"] for edge in ordered_edges],
        },
        "nodes": ordered_nodes,
        "edges": ordered_edges,
    }


def run_inspector_from_events(events: list[Any]) -> dict:
    agents: dict[str, dict[str, Any]] = {}
    phase = "created"
    error_events = {"worker_step_failed", "worker_step_blocked", "llm_unavailable", "task_failed"}
    for event in events:
        payload = event.payload if isinstance(event.payload, Mapping) else {}
        agent_id = event.agent_id or payload.get("agent_id")
        if agent_id:
            agent = agents.setdefault(
                str(agent_id),
                {"agent_id": str(agent_id), "role": payload.get("agent_role"), "status": "pending", "last_event": None},
            )
            agent["role"] = agent["role"] or payload.get("agent_role")
            agent["last_event"] = event.event_type
            agent["status"] = _agent_status_for_event(event.event_type)
        phase = _phase_for_event(event.event_type, phase)

    return {
        "phase": phase,
        "metrics": {
            "event_count": len(events),
            "route_count": sum(event.event_type == "swarm_route_selected" for event in events),
            "tool_count": sum(event.event_type == "tool_execution_completed" for event in events),
            "error_count": sum(event.event_type in error_events for event in events),
        },
        "agents": list(agents.values()),
    }


def quality_from_events(events: list[Any]) -> dict:
    worker_steps = [
        event for event in events
        if event.event_type in {"worker_step_completed", "worker_step_failed", "worker_step_blocked"}
    ]
    evidence_events = [event for event in events if event.event_type == "tool_execution_completed"]
    verdict_events = [event for event in events if event.event_type == "audit_verdict"]
    passed_verdicts = [
        event for event in verdict_events
        if isinstance(event.payload, Mapping) and event.payload.get("verdict") == "pass"
    ]
    correction_events = [event for event in events if event.event_type == "correction_requested"]
    replay_points = []
    for event in events:
        if event.event_type not in {"correction_requested", "audit_verdict"}:
            continue
        payload = event.payload if isinstance(event.payload, Mapping) else {}
        if event.event_type == "audit_verdict" and payload.get("verdict") == "pass":
            continue
        replay_points.append(
            {
                "event_id": str(event.id),
                "sequence": event.sequence,
                "event_type": event.event_type,
                "agent_id": event.agent_id,
                "reason": payload.get("summary") or payload.get("required_corrections") or "review required",
            }
        )

    evidence_coverage = (
        min(len(worker_steps), len(evidence_events)) / len(worker_steps)
        if worker_steps
        else 0.0
    )
    audit_pass_rate = len(passed_verdicts) / len(verdict_events) if verdict_events else 0.0
    return {
        "metrics": {
            "evidence_coverage": round(evidence_coverage, 4),
            "audit_pass_rate": round(audit_pass_rate, 4),
            "worker_step_count": len(worker_steps),
            "evidence_count": len(evidence_events),
            "audit_count": len(verdict_events),
            "correction_count": len(correction_events),
            "replay_point_count": len(replay_points),
        },
        "replay_points": replay_points,
    }


def resource_budget_from_events(events: list[Any]) -> dict:
    decisions = []
    for event in events:
        if event.event_type != "resource_allocation_decided" or not isinstance(event.payload, Mapping):
            continue
        decisions.append(event.payload)
    if not decisions:
        return {
            "budget": {"max_parallel_branches": 0, "max_retries": 0, "max_tokens": 0},
            "usage": {"active_branches": 0, "retries": 0, "tokens_used": 0},
            "metrics": {"admitted_count": 0, "rejected_count": 0},
            "last_reason": None,
        }
    latest = decisions[-1]
    return {
        "budget": _to_json_safe(latest.get("budget", {})),
        "usage": _to_json_safe(latest.get("usage", {})),
        "metrics": {
            "admitted_count": sum(bool(item.get("admitted")) for item in decisions),
            "rejected_count": sum(not bool(item.get("admitted")) for item in decisions),
        },
        "last_reason": latest.get("reason"),
    }


def checkpoints_from_events(events: list[Any]) -> list[dict]:
    checkpoint_events = {
        "task_created",
        "planning_completed",
        "worker_step_completed",
        "worker_step_failed",
        "worker_step_blocked",
        "audit_verdict",
        "chief_audit_verdict",
        "human_review_packet_created",
        "correction_requested",
        "replay_waiting_approval",
        "task_completed",
        "task_failed",
        "task_blocked",
        "task_waiting_approval",
    }
    terminal_phases = {"completed", "failed", "blocked"}
    checkpoints = []
    phase = "created"
    for event in events:
        if event.event_type not in checkpoint_events:
            continue
        phase = _phase_for_event(event.event_type, phase)
        checkpoints.append(
            {
                "event_id": str(event.id),
                "sequence": event.sequence,
                "phase": phase,
                "status": phase,
                "resumable": phase not in terminal_phases,
                "state_refs": {
                    "task_id": str(event.task_id),
                    "trace_id": str(event.trace_id),
                },
            }
        )
    return checkpoints


def memory_notes_from_events(events: list[Any], *, query: str | None = None, limit: int = 20) -> list[dict]:
    normalized_query = _memory_tokens(query or "")
    notes = []
    for event in events:
        if event.event_type != "memory_note_added" or not isinstance(event.payload, Mapping):
            continue
        payload = event.payload
        searchable = _memory_tokens(
            " ".join(
                [
                    str(payload.get("kind", "")),
                    str(payload.get("title", "")),
                    str(payload.get("content", "")),
                    " ".join(str(tag) for tag in payload.get("tags", [])),
                ]
            )
        )
        score = len(normalized_query & searchable) if normalized_query else 0
        if normalized_query and score == 0:
            continue
        notes.append(
            {
                "memory_id": payload.get("memory_id", str(event.id)),
                "event_id": str(event.id),
                "task_id": str(event.task_id),
                "sequence": event.sequence,
                "kind": payload.get("kind"),
                "title": payload.get("title"),
                "content": payload.get("content"),
                "parameter_key": payload.get("parameter_key"),
                "parameter_value": payload.get("parameter_value"),
                "tags": _to_json_safe(payload.get("tags", [])),
                "refs": _to_json_safe(payload.get("refs", [])),
                "score": score,
                "created_at": _serialize_datetime(event.created_at),
            }
        )
    notes.sort(key=lambda note: (-note["score"], -note["sequence"]))
    return notes[:limit]


def memory_graph_from_events(events: list[Any]) -> dict:
    nodes: dict[str, dict] = {}
    edges = []
    for event in events:
        payload = event.payload if isinstance(event.payload, Mapping) else {}
        if event.event_type == "memory_note_added":
            memory_id = str(payload.get("memory_id", getattr(event, "id", "unknown")))
            nodes[memory_id] = {
                "memory_id": memory_id,
                "task_id": str(event.task_id),
                "kind": payload.get("kind"),
                "title": payload.get("title"),
                "content": payload.get("content"),
                "parameter_key": payload.get("parameter_key"),
                "parameter_value": payload.get("parameter_value"),
            }
        elif event.event_type == "memory_relation_added":
            source = str(payload.get("source_memory_id", ""))
            target = str(payload.get("target_memory_id", ""))
            if not source or not target:
                continue
            nodes.setdefault(source, {"memory_id": source, "missing": True})
            nodes.setdefault(target, {"memory_id": target, "missing": True})
            edges.append(
                {
                    "relation_id": str(payload.get("relation_id", getattr(event, "id", "unknown"))),
                    "source_memory_id": source,
                    "target_memory_id": target,
                    "relation": payload.get("relation"),
                    "reason": payload.get("reason"),
                    "task_id": str(event.task_id),
                }
            )
    parameter_groups: dict[str, list[dict]] = {}
    for node in nodes.values():
        key = node.get("parameter_key")
        if key and node.get("parameter_value") is not None:
            parameter_groups.setdefault(str(key), []).append(node)
    for key, group in parameter_groups.items():
        for left_index, left in enumerate(group):
            for right in group[left_index + 1 :]:
                if left.get("parameter_value") == right.get("parameter_value"):
                    continue
                edges.append(
                    {
                        "relation_id": f"parameter-conflict:{left['memory_id']}:{right['memory_id']}",
                        "source_memory_id": left["memory_id"],
                        "target_memory_id": right["memory_id"],
                        "relation": "parameter_conflict",
                        "reason": f"Different values for {key}: {left['parameter_value']} vs {right['parameter_value']}",
                        "task_id": left.get("task_id"),
                    }
                )
    conflicts = [edge for edge in edges if edge.get("relation") in {"contradicts", "parameter_conflict"}]
    return {
        "summary": {"node_count": len(nodes), "edge_count": len(edges), "conflict_count": len(conflicts)},
        "nodes": sorted(nodes.values(), key=lambda node: node["memory_id"]),
        "edges": edges,
        "conflicts": conflicts,
    }


def research_plan_from_events(events: list[Any]) -> dict | None:
    plans = [
        event for event in events
        if event.event_type == "research_plan_created" and isinstance(event.payload, Mapping)
    ]
    if not plans:
        return None
    event = plans[-1]
    return {**dict(event.payload), "event_id": str(event.id)}


def _memory_tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-zA-Zа-яА-Я0-9_]{2,}", value.lower())}


def _phase_for_event(event_type: str, current: str) -> str:
    phases = {
        "task_created": "created",
        "task_started": "planning",
        "planning_started": "planning",
        "worker_step_started": "execution",
        "worker_step_completed": "execution",
        "worker_step_failed": "execution",
        "worker_step_blocked": "execution",
        "audit_verdict": "audit",
        "chief_audit_verdict": "final_gate",
        "human_review_packet_created": "human_review",
        "task_completed": "completed",
        "task_failed": "failed",
        "task_blocked": "blocked",
        "task_waiting_approval": "waiting_approval",
    }
    return phases.get(event_type, current)


def _agent_status_for_event(event_type: str) -> str:
    if event_type in {"worker_step_completed", "audit_verdict", "chief_audit_verdict"}:
        return "completed"
    if event_type in {"worker_step_failed", "worker_step_blocked", "llm_unavailable"}:
        return "blocked"
    if event_type in {"human_review_packet_created"}:
        return "waiting"
    return "running"


def _graph_node(node_id: str, *, endpoint_role: str | None = None) -> dict:
    role = _agent_role(node_id, endpoint_role)
    pair_id = _pair_id(node_id) if role in {"worker", "auditor"} else None
    return {
        "id": node_id,
        "label": _agent_label(node_id, role),
        "role": role,
        "endpoint_role": endpoint_role or role,
        "pair_id": pair_id,
        "incoming_count": 0,
        "outgoing_count": 0,
        "first_sequence": None,
        "last_sequence": None,
    }


def _agent_role(node_id: str, endpoint_role: str | None) -> str:
    if node_id.startswith("worker-"):
        return "worker"
    if node_id.startswith("auditor-"):
        return "auditor"
    if endpoint_role == "assigned_auditor":
        return "auditor"
    if endpoint_role == "chief_auditor":
        return "chief_auditor"
    return endpoint_role or node_id


def _pair_id(node_id: str) -> str | None:
    suffix = node_id.removeprefix("worker-").removeprefix("auditor-")
    if not suffix or suffix == node_id:
        return None
    return f"worker-{suffix}:auditor-{suffix}"


def _agent_label(node_id: str, role: str) -> str:
    if role == "worker" and node_id.startswith("worker-"):
        return f"Worker {node_id.removeprefix('worker-')}"
    if role == "auditor" and node_id.startswith("auditor-"):
        return f"Auditor {node_id.removeprefix('auditor-')}"
    if role == "chief_auditor":
        return "Chief Auditor"
    return node_id.replace("_", " ").title()


def _event_to_public_dict(event: Any) -> dict:
    payload = _strip_raw_reasoning_content(_to_json_safe(event.payload))
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


def _strip_raw_reasoning_content(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _strip_raw_reasoning_content(item)
            for key, item in value.items()
            if key != "raw_reasoning_content"
        }
    if isinstance(value, list):
        return [_strip_raw_reasoning_content(item) for item in value]
    return value
