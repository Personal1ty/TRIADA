from __future__ import annotations

from pathlib import Path

from app.tools.base import ToolRequest, ToolResult
from app.tools.shell import ShellTool


class GitTool:
    tool_name = "git"
    _ALLOWED = {"status", "diff", "log"}
    _BLOCKED_FLAGS = {"--no-index", "--ext-diff", "--external-diff", "-c"}

    def __init__(self, *, workspace: str | Path, timeout_seconds: float = 30) -> None:
        self.workspace = Path(workspace).resolve()
        self.shell = ShellTool(
            allowlist={"git"},
            workspace=self.workspace,
            timeout_seconds=timeout_seconds,
        )

    def is_command_allowed(self, command: list[str]) -> bool:
        if len(command) < 2 or command[0] != "git":
            return False
        if command[1] in self._BLOCKED_FLAGS:
            return False
        if command[1] not in self._ALLOWED:
            return False
        if any(arg in self._BLOCKED_FLAGS for arg in command[2:]):
            return False
        return self._path_operands_stay_in_workspace(command)

    def validate_input(self, request: ToolRequest) -> None:
        if not self.is_command_allowed(request.command):
            raise PermissionError(f"git command '{' '.join(request.command)}' is not allowlisted")
        self.shell.validate_input(request)

    async def dry_run(self, request: ToolRequest) -> ToolResult:
        self.validate_input(request)
        return await self.shell.dry_run(request)

    async def execute(self, request: ToolRequest) -> ToolResult:
        self.validate_input(request)
        result = await self.shell.execute(request)
        return result.model_copy(update={"tool": self.tool_name})

    def validate_result(self, result: ToolResult) -> None:
        self.shell.validate_result(result)

    async def rollback(self, request: ToolRequest, result: ToolResult) -> ToolResult | None:
        return None

    def _path_operands_stay_in_workspace(self, command: list[str]) -> bool:
        for arg in command[2:]:
            if arg.startswith("-"):
                continue
            path = Path(arg)
            if path.is_absolute() or any(part == ".." for part in path.parts):
                resolved = path.resolve() if path.is_absolute() else (self.workspace / path).resolve()
                if resolved != self.workspace and not resolved.is_relative_to(self.workspace):
                    return False
        return True
