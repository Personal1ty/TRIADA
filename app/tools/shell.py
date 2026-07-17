from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from app.audit.redaction import redact_text
from app.tools.base import ToolAdapter, ToolRequest, ToolResult, ensure_risk_allowed


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
    ) -> None:
        self.allowlist = allowlist
        self.workspace = Path(workspace).resolve()
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes
        self.secrets = tuple(secret for secret in (secrets or ()) if secret)

    def validate_input(self, request: ToolRequest) -> None:
        if not request.command:
            raise ValueError("command is required")
        if request.command[0] not in self.allowlist:
            raise PermissionError(f"command '{request.command[0]}' is not allowlisted")
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
        started_at = datetime.now(UTC)
        process = await asyncio.create_subprocess_exec(
            *request.command,
            cwd=cwd,
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
            process.kill()
            stdout_bytes, stderr_bytes = await process.communicate()
        finished_at = datetime.now(UTC)
        return ToolResult(
            tool=self.tool_name,
            command=request.command,
            exit_code=process.returncode if process.returncode is not None else -1,
            stdout=self._clean_output(stdout_bytes),
            stderr=self._clean_output(stderr_bytes),
            timed_out=timed_out,
            started_at=started_at,
            finished_at=finished_at,
            metadata={"cwd": str(cwd)},
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

    def _clean_output(self, value: bytes) -> str:
        truncated = value[: self.max_output_bytes]
        text = truncated.decode("utf-8", errors="replace")
        text = redact_text(text)
        for secret in self.secrets:
            text = text.replace(secret, "[REDACTED]")
        if len(value) > self.max_output_bytes:
            text += "\n[TRUNCATED]"
        return text
