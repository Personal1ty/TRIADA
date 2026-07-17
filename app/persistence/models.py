from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_status", "status"),
        Index("ix_tasks_trace_id_created_at", "trace_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="created")
    risk: Mapped[str | None] = mapped_column(String(64))
    constraints: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    allowed_tools: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    acceptance_criteria: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    timeout_seconds: Mapped[int | None] = mapped_column(Integer)
    retry_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)


class TaskStep(Base):
    __tablename__ = "task_steps"
    __table_args__ = (
        Index("ix_task_steps_task_id_created_at", "task_id", "created_at"),
        Index("ix_task_steps_status", "status"),
        Index("ix_task_steps_stage", "stage"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    stage: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="pending")
    description: Mapped[str | None] = mapped_column(Text)
    dependencies: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    input_contract: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    output_contract: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    timeout_seconds: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        Index("ix_agent_runs_trace_id_created_at", "trace_id", "created_at"),
        Index("ix_agent_runs_task_id_created_at", "task_id", "created_at"),
        Index("ix_agent_runs_agent_id_sequence", "agent_id", "sequence"),
        Index("ix_agent_runs_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id"), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(128), nullable=False)
    agent_role: Mapped[str] = mapped_column(String(64), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="pending")
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_trace_id_created_at", "trace_id", "created_at"),
        Index("ix_audit_events_task_id_created_at", "task_id", "created_at"),
        Index("ix_audit_events_agent_id_sequence", "agent_id", "sequence"),
        Index("ix_audit_events_event_type", "event_type"),
        Index("ix_audit_events_sequence", "trace_id", "sequence"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    task_id: Mapped[str] = mapped_column(String(36), nullable=False)
    agent_id: Mapped[str | None] = mapped_column(String(128))
    span_id: Mapped[str | None] = mapped_column(String(36))
    parent_span_id: Mapped[str | None] = mapped_column(String(36))
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    previous_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)


class ThinkingSummaryDelta(Base):
    __tablename__ = "thinking_summary_deltas"
    __table_args__ = (
        Index("ix_thinking_summary_deltas_trace_id_created_at", "trace_id", "created_at"),
        Index("ix_thinking_summary_deltas_task_id_created_at", "task_id", "created_at"),
        Index("ix_thinking_summary_deltas_agent_id_sequence", "agent_id", "sequence"),
        Index("ix_thinking_summary_deltas_stage", "stage"),
        Index("ix_thinking_summary_deltas_source", "source"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), ForeignKey("audit_events.id"), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    task_id: Mapped[str] = mapped_column(String(36), nullable=False)
    span_id: Mapped[str] = mapped_column(String(36), nullable=False)
    parent_span_id: Mapped[str | None] = mapped_column(String(36))
    agent_id: Mapped[str] = mapped_column(String(128), nullable=False)
    agent_role: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    stage: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    observations: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    input_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    output_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    next_step: Mapped[str | None] = mapped_column(String(500))
    progress_percent: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)


class ReasoningSummary(Base):
    __tablename__ = "reasoning_summaries"
    __table_args__ = (
        Index("ix_reasoning_summaries_trace_id_created_at", "trace_id", "created_at"),
        Index("ix_reasoning_summaries_task_id_created_at", "task_id", "created_at"),
        Index("ix_reasoning_summaries_agent_id_sequence", "agent_id", "sequence"),
        Index("ix_reasoning_summaries_source", "source"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    task_id: Mapped[str] = mapped_column(String(36), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)


class ToolExecution(Base):
    __tablename__ = "tool_executions"
    __table_args__ = (
        Index("ix_tool_executions_trace_id_created_at", "trace_id", "created_at"),
        Index("ix_tool_executions_task_id_created_at", "task_id", "created_at"),
        Index("ix_tool_executions_agent_id_sequence", "agent_id", "sequence"),
        Index("ix_tool_executions_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    task_id: Mapped[str] = mapped_column(String(36), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(128), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    tool: Mapped[str] = mapped_column(String(128), nullable=False)
    command: Mapped[list | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="created")
    exit_code: Mapped[int | None] = mapped_column(Integer)
    stdout_ref: Mapped[str | None] = mapped_column(Text)
    stderr_ref: Mapped[str | None] = mapped_column(Text)
    timed_out: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)


class Artifact(Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        Index("ix_artifacts_trace_id_created_at", "trace_id", "created_at"),
        Index("ix_artifacts_task_id_created_at", "task_id", "created_at"),
        Index("ix_artifacts_source", "source"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    task_id: Mapped[str] = mapped_column(String(36), nullable=False)
    agent_id: Mapped[str | None] = mapped_column(String(128))
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="runtime")
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    path: Mapped[str | None] = mapped_column(Text)
    artifact_type: Mapped[str] = mapped_column(String(128), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(128))
    checksum: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)


class ValidationResult(Base):
    __tablename__ = "validation_results"
    __table_args__ = (
        Index("ix_validation_results_trace_id_created_at", "trace_id", "created_at"),
        Index("ix_validation_results_task_id_created_at", "task_id", "created_at"),
        Index("ix_validation_results_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    task_id: Mapped[str] = mapped_column(String(36), nullable=False)
    agent_id: Mapped[str | None] = mapped_column(String(128))
    check_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)


class AuditVerdict(Base):
    __tablename__ = "audit_verdicts"
    __table_args__ = (
        Index("ix_audit_verdicts_trace_id_created_at", "trace_id", "created_at"),
        Index("ix_audit_verdicts_task_id_created_at", "task_id", "created_at"),
        Index("ix_audit_verdicts_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    task_id: Mapped[str] = mapped_column(String(36), nullable=False)
    agent_id: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    violations: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    required_corrections: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    evidence_event_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)


class TaskCheckpoint(Base):
    __tablename__ = "task_checkpoints"
    __table_args__ = (
        Index("ix_task_checkpoints_trace_id_created_at", "trace_id", "created_at"),
        Index("ix_task_checkpoints_task_id_created_at", "task_id", "created_at"),
        Index("ix_task_checkpoints_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    task_id: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    checkpoint_type: Mapped[str] = mapped_column(String(128), nullable=False, default="runtime")
    state: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
