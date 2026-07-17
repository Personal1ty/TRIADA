from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CreateTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: str = Field(min_length=1, max_length=20_000)
    risk: str | None = Field(default=None, max_length=64)
    constraints: dict[str, Any] = Field(default_factory=dict)
    allowed_tools: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    timeout_seconds: int | None = Field(default=None, ge=1)
    retry_limit: int = Field(default=0, ge=0)
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


class TaskEventsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    trace_id: str
    events: list[dict[str, Any]]


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved: bool = True
    approved_by: str | None = Field(default=None, max_length=255)
    reason: str | None = Field(default=None, max_length=2_000)


class TaskActionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    trace_id: str
    status: str
    action: str
