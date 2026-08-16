from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.tools.base import ToolAdapter, ToolRequest, ToolResult, ensure_risk_allowed


class WriteFileTool(ToolAdapter):
    tool_name = "write_file"

    def __init__(self, *, workspace: str | Path) -> None:
        self.workspace = Path(workspace).resolve()

    def validate_input(self, request: ToolRequest) -> None:
        if len(request.command) != 3 or request.command[0] != self.tool_name:
            raise ValueError("write_file command must be: write_file <relative-path> <content>")
        ensure_risk_allowed(request)
        self._resolve_target(request.command[1])

    async def dry_run(self, request: ToolRequest) -> ToolResult:
        self.validate_input(request)
        now = datetime.now(UTC)
        target = self._resolve_target(request.command[1])
        return ToolResult(
            tool=self.tool_name,
            command=request.command,
            exit_code=0,
            started_at=now,
            finished_at=now,
            metadata={"dry_run": True, "target": str(target)},
        )

    async def execute(self, request: ToolRequest) -> ToolResult:
        self.validate_input(request)
        started_at = datetime.now(UTC)
        target = self._resolve_target(request.command[1])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(request.command[2], encoding="utf-8")
        finished_at = datetime.now(UTC)
        return ToolResult(
            tool=self.tool_name,
            command=request.command,
            exit_code=0,
            stdout=f"wrote {target.relative_to(self.workspace)}\n",
            started_at=started_at,
            finished_at=finished_at,
            metadata={"target": str(target), "bytes": len(request.command[2].encode("utf-8"))},
        )

    def validate_result(self, result: ToolResult) -> None:
        if result.exit_code != 0:
            raise RuntimeError(result.stderr or "write_file failed")

    async def rollback(self, request: ToolRequest, result: ToolResult) -> ToolResult | None:
        return None

    def _resolve_target(self, raw_path: str) -> Path:
        path = Path(raw_path)
        if path.is_absolute() or any(part == ".." for part in path.parts):
            raise PermissionError("write_file target must stay inside workspace")
        target = (self.workspace / path).resolve()
        if target == self.workspace or not target.is_relative_to(self.workspace):
            raise PermissionError("write_file target must stay inside workspace")
        return target
