from __future__ import annotations

from pathlib import Path

from app.tools.base import ToolRequest, ToolResult
from app.tools.shell import ShellTool


class KubernetesReadOnlyTool:
    tool_name = "kubernetes"
    _ALLOWED = {"get", "describe", "logs"}

    def __init__(self, *, workspace: str | Path, timeout_seconds: float = 60) -> None:
        self.shell = ShellTool(
            allowlist={"kubectl"},
            workspace=workspace,
            timeout_seconds=timeout_seconds,
        )

    def is_command_allowed(self, command: list[str]) -> bool:
        return len(command) >= 2 and command[0] == "kubectl" and command[1] in self._ALLOWED

    def validate_input(self, request: ToolRequest) -> None:
        if not self.is_command_allowed(request.command):
            raise PermissionError(f"kubectl command '{' '.join(request.command)}' is not allowlisted")
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
