from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.tools.base import ToolAdapter, ToolRequest, ToolResult, ensure_risk_allowed


class ApplyPatchTool(ToolAdapter):
    tool_name = "apply_patch"

    def __init__(self, *, workspace: str | Path) -> None:
        self.workspace = Path(workspace).resolve()

    def validate_input(self, request: ToolRequest) -> None:
        if len(request.command) != 4 or request.command[0] != self.tool_name:
            raise ValueError("apply_patch command must be: apply_patch <relative-path> <old-text> <new-text>")
        ensure_risk_allowed(request)
        target = self._resolve_target(request.command[1])
        if not target.is_file():
            raise FileNotFoundError(f"apply_patch target does not exist: {request.command[1]}")

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
        old_text = request.command[2]
        new_text = request.command[3]
        content = target.read_text(encoding="utf-8")
        if old_text not in content:
            raise ValueError("apply_patch old text was not found in target")
        patched = content.replace(old_text, new_text, 1)
        target.write_text(patched, encoding="utf-8")
        finished_at = datetime.now(UTC)
        return ToolResult(
            tool=self.tool_name,
            command=request.command,
            exit_code=0,
            stdout=f"patched {target.relative_to(self.workspace)}\n",
            started_at=started_at,
            finished_at=finished_at,
            metadata={
                "target": str(target),
                "old_bytes": len(old_text.encode("utf-8")),
                "new_bytes": len(new_text.encode("utf-8")),
            },
        )

    def validate_result(self, result: ToolResult) -> None:
        if result.exit_code != 0:
            raise RuntimeError(result.stderr or "apply_patch failed")

    async def rollback(self, request: ToolRequest, result: ToolResult) -> ToolResult | None:
        return None

    def _resolve_target(self, raw_path: str) -> Path:
        path = Path(raw_path)
        if path.is_absolute() or any(part == ".." for part in path.parts):
            raise PermissionError("apply_patch target must stay inside workspace")
        target = (self.workspace / path).resolve()
        if target == self.workspace or not target.is_relative_to(self.workspace):
            raise PermissionError("apply_patch target must stay inside workspace")
        return target
