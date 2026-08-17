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
