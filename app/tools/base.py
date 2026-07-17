from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.audit.redaction import redact_text
from app.schemas.enums import RiskPolicy


class ToolRequest(BaseModel):
    command: list[str] = Field(min_length=1)
    working_dir: Path | None = None
    risk_policy: RiskPolicy
    approval_ref: str | None = None
    expected_change: str | None = None
    validation_command: list[str] | None = None
    rollback_action: str | None = None


class ToolResult(BaseModel):
    tool: str
    command: list[str]
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    started_at: datetime
    finished_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


def ensure_risk_allowed(request: ToolRequest) -> None:
    if request.risk_policy == RiskPolicy.READ_ONLY:
        return
    if request.risk_policy == RiskPolicy.LOW_RISK_WRITE:
        if not request.expected_change:
            raise PermissionError("LOW_RISK_WRITE requires expected_change")
        if not request.validation_command:
            raise PermissionError("LOW_RISK_WRITE requires validation_command")
        return
    if request.risk_policy in {RiskPolicy.HIGH_RISK_WRITE, RiskPolicy.DESTRUCTIVE}:
        if not request.approval_ref:
            raise PermissionError(f"{request.risk_policy} requires approval reference")
        return
    raise PermissionError(f"unsupported risk policy: {request.risk_policy}")


def clean_tool_output(value: bytes | str, *, max_output_bytes: int, secrets: tuple[str, ...] = ()) -> str:
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
    text = redact_text(text)
    for secret in secrets:
        text = text.replace(secret, "[REDACTED]")
    raw = text.encode("utf-8", errors="replace")
    if len(raw) <= max_output_bytes:
        return text
    return raw[:max_output_bytes].decode("utf-8", errors="replace") + "\n[TRUNCATED]"


class ToolAdapter(ABC):
    tool_name: str

    @abstractmethod
    def validate_input(self, request: ToolRequest) -> None:
        raise NotImplementedError

    @abstractmethod
    async def dry_run(self, request: ToolRequest) -> ToolResult:
        raise NotImplementedError

    @abstractmethod
    async def execute(self, request: ToolRequest) -> ToolResult:
        raise NotImplementedError

    @abstractmethod
    def validate_result(self, result: ToolResult) -> None:
        raise NotImplementedError

    @abstractmethod
    async def rollback(self, request: ToolRequest, result: ToolResult) -> ToolResult | None:
        raise NotImplementedError
