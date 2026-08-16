from __future__ import annotations

from pathlib import Path

from app.tools.base import ToolRequest, ToolResult
from app.tools.shell import ShellTool
from app.schemas.enums import RiskPolicy


class GitTool:
    tool_name = "git"
    _READ_ONLY = {"status", "diff", "log"}
    _WRITE = {"add", "commit", "push"}
    _BLOCKED_FLAGS = {"--no-index", "--ext-diff", "--external-diff", "-c"}
    _BLOCKED_VALUE_OPTIONS = {
        "--output",
        "--pathspec-from-file",
        "--git-dir",
        "--work-tree",
        "--namespace",
    }

    def __init__(self, *, workspace: str | Path, timeout_seconds: float = 30) -> None:
        self.workspace = Path(workspace).resolve()
        self.shell = ShellTool(
            allowlist={"git"},
            workspace=self.workspace,
            timeout_seconds=timeout_seconds,
        )

    def is_command_allowed(
        self,
        command: list[str],
        *,
        risk_policy: RiskPolicy = RiskPolicy.READ_ONLY,
        approval_ref: str | None = None,
    ) -> bool:
        if len(command) < 2 or command[0] != "git":
            return False
        if self._is_blocked_arg(command[1]):
            return False
        if command[1] in self._READ_ONLY:
            if risk_policy != RiskPolicy.READ_ONLY:
                return False
            if any(self._is_blocked_arg(arg) for arg in command[2:]):
                return False
            return self._path_operands_stay_in_workspace(command)
        if command[1] not in self._WRITE:
            return False
        if any(self._is_blocked_arg(arg) for arg in command[2:]):
            return False
        if risk_policy not in {RiskPolicy.HIGH_RISK_WRITE, RiskPolicy.DESTRUCTIVE} or not approval_ref:
            return False
        return self._is_write_command_shape_allowed(command) and self._path_operands_stay_in_workspace(command)

    def validate_input(self, request: ToolRequest) -> None:
        if not self.is_command_allowed(
            request.command,
            risk_policy=request.risk_policy,
            approval_ref=request.approval_ref,
        ):
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

    def _is_blocked_arg(self, arg: str) -> bool:
        if arg in self._BLOCKED_FLAGS or arg in self._BLOCKED_VALUE_OPTIONS:
            return True
        option, separator, _value = arg.partition("=")
        return bool(separator) and option in self._BLOCKED_VALUE_OPTIONS

    def _path_operands_stay_in_workspace(self, command: list[str]) -> bool:
        for arg in command[2:]:
            if arg.startswith("-"):
                continue
            if command[1] == "commit" and command[2:4] == ["-m", arg]:
                continue
            if command[1] == "push" and arg in {"origin", "main", "master"}:
                continue
            if command[1] == "push" and arg.replace("-", "").replace("_", "").replace("/", "").isalnum():
                continue
            path = Path(arg)
            if path.is_absolute() or any(part == ".." for part in path.parts):
                resolved = path.resolve() if path.is_absolute() else (self.workspace / path).resolve()
                if resolved != self.workspace and not resolved.is_relative_to(self.workspace):
                    return False
        return True

    def _is_write_command_shape_allowed(self, command: list[str]) -> bool:
        subcommand = command[1]
        if subcommand == "add":
            return len(command) >= 3 and all(not arg.startswith("-") for arg in command[2:])
        if subcommand == "commit":
            return len(command) == 4 and command[2] == "-m" and bool(command[3].strip())
        if subcommand == "push":
            return (
                len(command) == 4
                and command[2] == "origin"
                and bool(command[3].strip())
                and not command[3].startswith("-")
            )
        return False
