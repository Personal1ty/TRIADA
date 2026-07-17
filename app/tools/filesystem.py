from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.schemas.enums import RiskPolicy
from app.tools.base import ToolAdapter, ToolRequest, ToolResult, ensure_risk_allowed


class FileSystemTool(ToolAdapter):
    tool_name = "filesystem"

    def __init__(self, *, workspace: str | Path) -> None:
        self.workspace = Path(workspace).resolve()

    def validate_input(self, request: ToolRequest) -> None:
        if not request.command:
            raise ValueError("command is required")
        if request.command[0] not in {"read", "list", "write"}:
            raise PermissionError(f"filesystem command '{request.command[0]}' is not allowlisted")
        if len(request.command) < 2:
            raise ValueError("filesystem command requires a path")
        self._resolve_path(request.command[1])
        if request.command[0] == "write" and request.risk_policy == RiskPolicy.READ_ONLY:
            raise PermissionError("filesystem write requires a write risk policy")
        ensure_risk_allowed(request)

    async def dry_run(self, request: ToolRequest) -> ToolResult:
        self.validate_input(request)
        now = datetime.now(UTC)
        return ToolResult(
            tool=self.tool_name,
            command=request.command,
            exit_code=0,
            started_at=now,
            finished_at=now,
            metadata={"dry_run": True},
        )

    async def execute(self, request: ToolRequest) -> ToolResult:
        self.validate_input(request)
        started_at = datetime.now(UTC)
        action = request.command[0]
        target = self._resolve_path(request.command[1])
        if action == "read":
            stdout = target.read_text()
        elif action == "list":
            stdout = "\n".join(sorted(path.name for path in target.iterdir()))
        else:
            if len(request.command) < 3:
                raise ValueError("write command requires content")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(request.command[2])
            stdout = str(target.relative_to(self.workspace))
        finished_at = datetime.now(UTC)
        return ToolResult(
            tool=self.tool_name,
            command=request.command,
            exit_code=0,
            stdout=stdout,
            started_at=started_at,
            finished_at=finished_at,
        )

    def validate_result(self, result: ToolResult) -> None:
        if result.exit_code != 0:
            raise RuntimeError(result.stderr or "filesystem command failed")

    async def rollback(self, request: ToolRequest, result: ToolResult) -> ToolResult | None:
        return None

    def _resolve_path(self, value: str) -> Path:
        path = Path(value)
        if not path.is_absolute():
            path = self.workspace / path
        resolved = path.resolve()
        if resolved != self.workspace and not resolved.is_relative_to(self.workspace):
            raise PermissionError("path is outside workspace")
        return resolved
