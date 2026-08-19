from __future__ import annotations

from typing import Any


_CAPABILITIES: dict[str, dict[str, Any]] = {
    "orchestrator": {
        "allowed": ["plan_task", "route_work", "read_memory", "propose_tools"],
        "denied": ["execute_tools", "issue_verdict", "approve_task"],
    },
    "worker": {
        "allowed": ["execute_tools", "read_memory", "write_artifacts", "report_result"],
        "denied": ["plan_task", "issue_verdict", "approve_task"],
    },
    "auditor": {
        "allowed": ["read_events", "read_memory", "inspect_artifacts", "issue_verdict"],
        "denied": ["execute_tools", "write_artifacts", "approve_task"],
    },
}

_REGISTRY = {
    "execute_tools": {"owner": "worker", "risk_policy": "task_scoped", "approval_required": False, "audit_event": "tool_execution_completed"},
    "write_artifacts": {"owner": "worker", "risk_policy": "write_policy", "approval_required": True, "audit_event": "artifact_created"},
    "issue_verdict": {"owner": "auditor", "risk_policy": "audit_gate", "approval_required": False, "audit_event": "audit_verdict"},
    "read_memory": {"owner": "orchestrator|worker|auditor", "risk_policy": "read_only", "approval_required": False, "audit_event": "memory_read"},
}


def capability_matrix() -> dict[str, dict[str, Any]]:
    return {
        role: {"allowed": list(spec["allowed"]), "denied": list(spec["denied"])}
        for role, spec in _CAPABILITIES.items()
    }


def check_capability(role: str, capability: str) -> dict[str, Any]:
    normalized_role = role.strip().lower()
    normalized_capability = capability.strip().lower()
    spec = _CAPABILITIES.get(normalized_role)
    allowed = bool(spec and normalized_capability in spec["allowed"])
    reason = None if allowed else f"{normalized_role} is not allowed to {normalized_capability}"
    return {
        "role": normalized_role,
        "capability": normalized_capability,
        "allowed": allowed,
        "reason": reason,
    }


def capability_registry() -> dict[str, dict[str, Any]]:
    return {name: dict(spec) for name, spec in _REGISTRY.items()}
