from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class WriteMode(StrEnum):
    NONE = "none"
    CREATE_FILE = "create_file"
    PATCH = "patch"


class ResourceBudgetContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_parallel_branches: int = Field(default=0, ge=0)
    max_retries: int = Field(default=0, ge=0)
    max_tokens: int = Field(default=0, ge=0)
    max_duration_ms: int = Field(default=0, ge=0)


class ExecutionContract(BaseModel):
    """Orchestrator proposal after it is bounded by the policy gate."""

    model_config = ConfigDict(extra="forbid")

    allowed_tools: list[str] = Field(default_factory=list)
    allowed_paths: list[str] = Field(default_factory=list)
    forbidden_paths: list[str] = Field(default_factory=list)
    write_mode: WriteMode = WriteMode.NONE
    expected_artifacts: list[str] = Field(default_factory=list)
    validation_commands: list[list[str]] = Field(default_factory=list)
    output_schema: str | None = None
    approval_required: bool = False
    resource_budget: ResourceBudgetContract = Field(default_factory=ResourceBudgetContract)
