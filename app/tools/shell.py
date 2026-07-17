from __future__ import annotations

import asyncio
import os
import shutil
import signal
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from app.tools.base import ToolAdapter, ToolRequest, ToolResult, clean_tool_output, ensure_risk_allowed


_DEFAULT_TRUSTED_PATHS = (
    "/bin",
    "/usr/bin",
    "/usr/local/bin",
    "/opt/homebrew/bin",
)


class ShellTool(ToolAdapter):
    tool_name = "shell"

    def __init__(
        self,
        *,
        allowlist: set[str],
        workspace: str | Path,
        timeout_seconds: float = 30,
        max_output_bytes: int = 64_000,
        secrets: Iterable[str] | None = None,
        trusted_paths: Iterable[str | Path] | None = None,
    ) -> None:
        self.allowlist = allowlist
        self.workspace = Path(workspace).resolve()
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes
        self.secrets = tuple(secret for secret in (secrets or ()) if secret)
        self.trusted_paths = tuple(
            str(Path(path).resolve()) for path in (trusted_paths or _DEFAULT_TRUSTED_PATHS)
        )
        self._trusted_env = self._build_trusted_env()

    def validate_input(self, request: ToolRequest) -> None:
        if not request.command:
            raise ValueError("command is required")
        self._resolve_executable(request.command[0])
        self._resolve_working_dir(request.working_dir)
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
        cwd = self._resolve_working_dir(request.working_dir)
        executable = self._resolve_executable(request.command[0])
        exec_command = [str(executable), *request.command[1:]]
        started_at = datetime.now(UTC)
        process = await asyncio.create_subprocess_exec(
            *exec_command,
            cwd=cwd,
            env=self._trusted_env,
            start_new_session=os.name == "posix",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        timed_out = False
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(), timeout=self.timeout_seconds
            )
        except TimeoutError:
            timed_out = True
            self._kill_process_tree(process)
            stdout_bytes, stderr_bytes = await process.communicate()
        finished_at = datetime.now(UTC)
        return ToolResult(
            tool=self.tool_name,
            command=request.command,
            exit_code=process.returncode if process.returncode is not None else -1,
            stdout=clean_tool_output(
                stdout_bytes,
                max_output_bytes=self.max_output_bytes,
                secrets=self.secrets,
            ),
            stderr=clean_tool_output(
                stderr_bytes,
                max_output_bytes=self.max_output_bytes,
                secrets=self.secrets,
            ),
            timed_out=timed_out,
            started_at=started_at,
            finished_at=finished_at,
            metadata={"cwd": str(cwd), "executable": str(executable)},
        )

    def validate_result(self, result: ToolResult) -> None:
        if result.timed_out:
            raise TimeoutError(f"{result.tool} timed out")
        if result.exit_code != 0:
            raise RuntimeError(result.stderr or f"{result.tool} failed with exit code {result.exit_code}")

    async def rollback(self, request: ToolRequest, result: ToolResult) -> ToolResult | None:
        return None

    def _resolve_working_dir(self, working_dir: Path | None) -> Path:
        path = self.workspace if working_dir is None else Path(working_dir)
        if not path.is_absolute():
            path = self.workspace / path
        resolved = path.resolve()
        if resolved != self.workspace and not resolved.is_relative_to(self.workspace):
            raise PermissionError("working_dir is outside workspace")
        return resolved

    def _resolve_executable(self, command_name: str) -> Path:
        if Path(command_name).name != command_name or command_name in {".", ".."}:
            raise PermissionError("command executable must be an allowlisted basename")
        if command_name not in self.allowlist:
            raise PermissionError(f"command '{command_name}' is not allowlisted")
        resolved = shutil.which(command_name, path=os.pathsep.join(self.trusted_paths))
        if resolved is None:
            raise FileNotFoundError(f"allowlisted command '{command_name}' was not found in trusted paths")
        return Path(resolved).resolve()

    def _build_trusted_env(self) -> dict[str, str]:
        env = {"PATH": os.pathsep.join(self.trusted_paths)}
        for key in ("HOME", "LANG", "LC_ALL", "SYSTEMROOT", "WINDIR"):
            if key in os.environ:
                env[key] = os.environ[key]
        return env

    def _kill_process_tree(self, process: asyncio.subprocess.Process) -> None:
        if os.name == "posix" and process.pid is not None:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                return
            except ProcessLookupError:
                return
            except OSError:
                pass
        process.kill()
