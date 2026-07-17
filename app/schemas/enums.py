from enum import StrEnum


class AgentRole(StrEnum):
    ORCHESTRATOR = "orchestrator"
    WORKER = "worker"
    AUDITOR = "auditor"


class DeltaSource(StrEnum):
    RUNTIME = "runtime"
    MODEL = "model"


class TaskState(StrEnum):
    CREATED = "created"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    RUNNING = "running"
    VALIDATING = "validating"
    CORRECTIONS_REQUIRED = "corrections_required"
    RETRYING = "retrying"
    ROLLING_BACK = "rolling_back"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class WorkerState(StrEnum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    RUNNING = "running"
    WAITING = "waiting"
    VALIDATING = "validating"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    STALLED = "stalled"
    CANCELLED = "cancelled"


class RiskPolicy(StrEnum):
    READ_ONLY = "read_only"
    LOW_RISK_WRITE = "low_risk_write"
    HIGH_RISK_WRITE = "high_risk_write"
    DESTRUCTIVE = "destructive"


class AuditVerdictValue(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    CORRECTIONS_REQUIRED = "corrections_required"
    BLOCKED = "blocked"
