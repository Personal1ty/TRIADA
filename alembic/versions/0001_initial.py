from alembic import op
import sqlalchemy as sa


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def _base_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("trace_id", sa.String(length=36), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("risk", sa.String(length=64), nullable=True),
        sa.Column("constraints", sa.JSON(), nullable=False),
        sa.Column("allowed_tools", sa.JSON(), nullable=False),
        sa.Column("acceptance_criteria", sa.JSON(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=True),
        sa.Column("retry_limit", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tasks_status", "tasks", ["status"])
    op.create_index("ix_tasks_trace_id_created_at", "tasks", ["trace_id", "created_at"])

    op.create_table(
        "task_steps",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("dependencies", sa.JSON(), nullable=False),
        sa.Column("input_contract", sa.JSON(), nullable=False),
        sa.Column("output_contract", sa.JSON(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_task_steps_stage", "task_steps", ["stage"])
    op.create_index("ix_task_steps_status", "task_steps", ["status"])
    op.create_index("ix_task_steps_task_id_created_at", "task_steps", ["task_id", "created_at"])

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("trace_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=128), nullable=False),
        sa.Column("agent_role", sa.String(length=64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_base_columns(),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_runs_agent_id_sequence", "agent_runs", ["agent_id", "sequence"])
    op.create_index("ix_agent_runs_status", "agent_runs", ["status"])
    op.create_index("ix_agent_runs_task_id_created_at", "agent_runs", ["task_id", "created_at"])
    op.create_index("ix_agent_runs_trace_id_created_at", "agent_runs", ["trace_id", "created_at"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("trace_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=128), nullable=True),
        sa.Column("span_id", sa.String(length=36), nullable=True),
        sa.Column("parent_span_id", sa.String(length=36), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("previous_hash", sa.String(length=64), nullable=False),
        sa.Column("event_hash", sa.String(length=64), nullable=False),
        *_base_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trace_id", "sequence", name="uq_audit_events_trace_id_sequence"),
    )
    op.create_index("ix_audit_events_agent_id_sequence", "audit_events", ["agent_id", "sequence"])
    op.create_index("ix_audit_events_event_type", "audit_events", ["event_type"])
    op.create_index("ix_audit_events_sequence", "audit_events", ["trace_id", "sequence"])
    op.create_index("ix_audit_events_task_id_created_at", "audit_events", ["task_id", "created_at"])
    op.create_index("ix_audit_events_trace_id_created_at", "audit_events", ["trace_id", "created_at"])

    op.create_table(
        "thinking_summary_deltas",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("trace_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("span_id", sa.String(length=36), nullable=False),
        sa.Column("parent_span_id", sa.String(length=36), nullable=True),
        sa.Column("agent_id", sa.String(length=128), nullable=False),
        sa.Column("agent_role", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(length=128), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("observations", sa.JSON(), nullable=False),
        sa.Column("input_refs", sa.JSON(), nullable=False),
        sa.Column("output_refs", sa.JSON(), nullable=False),
        sa.Column("next_step", sa.String(length=500), nullable=True),
        sa.Column("progress_percent", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        *_base_columns(),
        sa.ForeignKeyConstraint(["event_id"], ["audit_events.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_thinking_summary_deltas_agent_id_sequence", "thinking_summary_deltas", ["agent_id", "sequence"])
    op.create_index("ix_thinking_summary_deltas_source", "thinking_summary_deltas", ["source"])
    op.create_index("ix_thinking_summary_deltas_stage", "thinking_summary_deltas", ["stage"])
    op.create_index("ix_thinking_summary_deltas_task_id_created_at", "thinking_summary_deltas", ["task_id", "created_at"])
    op.create_index("ix_thinking_summary_deltas_trace_id_created_at", "thinking_summary_deltas", ["trace_id", "created_at"])

    op.create_table(
        "reasoning_summaries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("trace_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=128), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        *_base_columns(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reasoning_summaries_agent_id_sequence", "reasoning_summaries", ["agent_id", "sequence"])
    op.create_index("ix_reasoning_summaries_source", "reasoning_summaries", ["source"])
    op.create_index("ix_reasoning_summaries_task_id_created_at", "reasoning_summaries", ["task_id", "created_at"])
    op.create_index("ix_reasoning_summaries_trace_id_created_at", "reasoning_summaries", ["trace_id", "created_at"])

    op.create_table(
        "tool_executions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("trace_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=128), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("tool", sa.String(length=128), nullable=False),
        sa.Column("command", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("stdout_ref", sa.Text(), nullable=True),
        sa.Column("stderr_ref", sa.Text(), nullable=True),
        sa.Column("timed_out", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_base_columns(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tool_executions_agent_id_sequence", "tool_executions", ["agent_id", "sequence"])
    op.create_index("ix_tool_executions_status", "tool_executions", ["status"])
    op.create_index("ix_tool_executions_task_id_created_at", "tool_executions", ["task_id", "created_at"])
    op.create_index("ix_tool_executions_trace_id_created_at", "tool_executions", ["trace_id", "created_at"])

    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("trace_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=128), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("path", sa.Text(), nullable=True),
        sa.Column("artifact_type", sa.String(length=128), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=True),
        sa.Column("checksum", sa.String(length=128), nullable=True),
        *_base_columns(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_artifacts_source", "artifacts", ["source"])
    op.create_index("ix_artifacts_task_id_created_at", "artifacts", ["task_id", "created_at"])
    op.create_index("ix_artifacts_trace_id_created_at", "artifacts", ["trace_id", "created_at"])

    op.create_table(
        "validation_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("trace_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=128), nullable=True),
        sa.Column("check_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        *_base_columns(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_validation_results_status", "validation_results", ["status"])
    op.create_index("ix_validation_results_task_id_created_at", "validation_results", ["task_id", "created_at"])
    op.create_index("ix_validation_results_trace_id_created_at", "validation_results", ["trace_id", "created_at"])

    op.create_table(
        "audit_verdicts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("trace_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("violations", sa.JSON(), nullable=False),
        sa.Column("required_corrections", sa.JSON(), nullable=False),
        sa.Column("evidence_event_ids", sa.JSON(), nullable=False),
        *_base_columns(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_verdicts_status", "audit_verdicts", ["status"])
    op.create_index("ix_audit_verdicts_task_id_created_at", "audit_verdicts", ["task_id", "created_at"])
    op.create_index("ix_audit_verdicts_trace_id_created_at", "audit_verdicts", ["trace_id", "created_at"])

    op.create_table(
        "task_checkpoints",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("trace_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("checkpoint_type", sa.String(length=128), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        *_base_columns(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_task_checkpoints_status", "task_checkpoints", ["status"])
    op.create_index("ix_task_checkpoints_task_id_created_at", "task_checkpoints", ["task_id", "created_at"])
    op.create_index("ix_task_checkpoints_trace_id_created_at", "task_checkpoints", ["trace_id", "created_at"])


def downgrade() -> None:
    for table in (
        "task_checkpoints",
        "audit_verdicts",
        "validation_results",
        "artifacts",
        "tool_executions",
        "reasoning_summaries",
        "thinking_summary_deltas",
        "audit_events",
        "agent_runs",
        "task_steps",
        "tasks",
    ):
        op.drop_table(table)
