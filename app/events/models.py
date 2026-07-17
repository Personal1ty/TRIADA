from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from app.audit.redaction import contains_secret
from app.schemas.enums import AgentRole, AuditVerdictValue, DeltaSource


ShortText = Annotated[str, Field(max_length=500)]
RefText = Annotated[str, Field(max_length=300)]

_UNSAFE_REASONING_PHRASES = (
    "let me think step by step",
    "hidden reasoning",
    "internal chain of thought",
    "chain-of-thought",
    "raw chain of thought",
    "system prompt",
)


def _walk_strings(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str):
                yield key
            yield from _walk_strings(item)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _walk_strings(item)


def _validate_public_safe_text(value: object) -> None:
    for text in _walk_strings(value):
        normalized = text.lower()
        if any(phrase in normalized for phrase in _UNSAFE_REASONING_PHRASES):
            raise ValueError("thinking summary contains unsafe reasoning text")
        if contains_secret(text):
            raise ValueError("thinking summary contains secret text")


class ThinkingSummaryDelta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    event_id: UUID
    trace_id: UUID
    task_id: UUID
    span_id: UUID
    parent_span_id: UUID | None = None
    agent_id: str
    agent_role: AgentRole
    source: DeltaSource
    sequence: int = Field(ge=1)
    stage: ShortText
    action: ShortText
    summary: Annotated[str, Field(max_length=1000)]
    observations: list[ShortText] = Field(default_factory=list, max_length=10)
    input_refs: list[RefText] = Field(default_factory=list)
    output_refs: list[RefText] = Field(default_factory=list)
    next_step: ShortText | None = None
    progress_percent: int | None = Field(default=None, ge=0, le=100)
    confidence: float | None = Field(default=None, ge=0, le=1)
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def reject_unsafe_text(self) -> "ThinkingSummaryDelta":
        _validate_public_safe_text(
            {
                "summary": self.summary,
                "observations": self.observations,
                "action": self.action,
                "stage": self.stage,
                "next_step": self.next_step,
                "input_refs": self.input_refs,
                "output_refs": self.output_refs,
                "metadata": self.metadata,
            }
        )
        return self


class AuditEventCreate(BaseModel):
    event_type: str
    trace_id: UUID
    task_id: UUID
    agent_id: str | None = None
    sequence: int | None = Field(default=None, ge=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolExecutionRecord(BaseModel):
    tool: str = Field(validation_alias=AliasChoices("tool", "tool_name"))
    command: list[str] | None = None
    risk_policy: str | None = None
    exit_code: int | None = None
    stdout_ref: str | None = None
    stderr_ref: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    timed_out: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ArtifactRecord(BaseModel):
    artifact_id: UUID | None = None
    name: str
    path: str | None = None
    artifact_type: str
    content_type: str | None = None
    checksum: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ValidationResultRecord(BaseModel):
    check_name: str
    passed: bool
    message: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AuditViolation(BaseModel):
    rule_id: str = Field(validation_alias=AliasChoices("rule_id", "code"))
    message: str
    severity: str = "error"
    evidence_event_ids: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("evidence_event_ids", "evidence_refs"),
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class AuditVerdict(BaseModel):
    verdict: AuditVerdictValue
    summary: str | None = None
    violations: list[AuditViolation] = Field(default_factory=list)
    required_corrections: list[str] = Field(default_factory=list)
    evidence_event_ids: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("evidence_event_ids", "evidence_refs"),
    )
    metadata: dict[str, Any] = Field(default_factory=dict)
