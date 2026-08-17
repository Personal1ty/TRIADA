from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.audit.redaction import contains_secret


class ResourceBudgetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_parallel_branches: int = Field(default=0, ge=0)
    max_retries: int = Field(default=0, ge=0)
    max_tokens: int = Field(default=0, ge=0)


class CreateTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: str = Field(min_length=1, max_length=20_000)
    risk: str | None = Field(default=None, max_length=64)
    constraints: dict[str, Any] = Field(default_factory=dict)
    allowed_tools: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    timeout_seconds: int | None = Field(default=None, ge=1)
    retry_limit: int = Field(default=0, ge=0)
    resource_budget: ResourceBudgetRequest = Field(default_factory=ResourceBudgetRequest)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("goal")
    @classmethod
    def goal_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("goal must not be blank")
        return value

    @field_validator("allowed_tools", "acceptance_criteria")
    @classmethod
    def list_items_must_not_be_blank(cls, value: list[str]) -> list[str]:
        cleaned = []
        for item in value:
            item = item.strip()
            if not item:
                raise ValueError("list items must not be blank")
            cleaned.append(item)
        return cleaned


class TaskResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    trace_id: str
    status: str


class TaskSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    trace_id: str
    status: str
    goal: str
    allowed_tools: list[str]
    created_at: str
    updated_at: str


class TaskListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tasks: list[TaskSummaryResponse]


class TaskEventsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    trace_id: str
    limit: int
    next_cursor: str | None = None
    has_more: bool = False
    raw_reasoning_refs: list[dict[str, Any]] = Field(default_factory=list)
    events: list[dict[str, Any]]


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved: bool = True
    approved_by: str | None = Field(default=None, max_length=255)
    reason: str | None = Field(default=None, max_length=2_000)


class ReplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_event_id: str = Field(min_length=1, max_length=64)
    requested_by: str | None = Field(default=None, max_length=255)
    reason: str | None = Field(default=None, max_length=2_000)


class MemoryNoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["decision", "observation", "constraint", "summary"]
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=4_000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    refs: list[str] = Field(default_factory=list, max_length=20)
    parameter_key: str | None = Field(default=None, max_length=200)
    parameter_value: str | None = Field(default=None, max_length=500)

    @field_validator("title", "content", "parameter_key", "parameter_value")
    @classmethod
    def text_must_be_safe(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("memory text must not be blank")
        if contains_secret(value):
            raise ValueError("memory text contains secret material")
        return value

    @field_validator("tags", "refs")
    @classmethod
    def refs_must_be_safe(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("memory tags and refs must not be blank")
        if any(contains_secret(value) for value in cleaned):
            raise ValueError("memory tags and refs contain secret material")
        return cleaned


class MemoryRelationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_memory_id: str = Field(min_length=1, max_length=64)
    target_memory_id: str = Field(min_length=1, max_length=64)
    relation: Literal[
        "supports",
        "contradicts",
        "derived_from",
        "supersedes",
        "depends_on",
        "validated_by",
    ]
    reason: str | None = Field(default=None, max_length=2_000)

    @field_validator("source_memory_id", "target_memory_id", "reason")
    @classmethod
    def relation_text_must_be_safe(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("relation text must not be blank")
        if contains_secret(value):
            raise ValueError("relation text contains secret material")
        return value


class ResearchPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=4_000)
    parameter_catalog: list[str] = Field(min_length=1, max_length=30)
    hypotheses: list[str] = Field(default_factory=list, max_length=20)
    depth: int = Field(default=1, ge=1, le=3)

    @field_validator("question", "parameter_catalog", "hypotheses")
    @classmethod
    def research_text_must_not_be_blank(cls, value):
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("research text must not be blank")
            if contains_secret(value):
                raise ValueError("research text contains secret material")
            return value
        cleaned = [item.strip() for item in value]
        if any(not item for item in cleaned):
            raise ValueError("research list items must not be blank")
        if any(contains_secret(item) for item in cleaned):
            raise ValueError("research list contains secret material")
        return cleaned


class DemoRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: str = Field(min_length=1, max_length=255)


class TaskActionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    trace_id: str
    status: str
    action: str


class RawReasoningRevealRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    acknowledge_sensitive: bool = False
    requested_by: str | None = Field(default=None, max_length=255)


class RawReasoningRevealResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    trace_id: str
    event_id: str
    agent_id: str | None
    raw_reasoning_content: str
