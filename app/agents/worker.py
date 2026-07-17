from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from app.events.models import ArtifactRecord, ValidationResultRecord
from app.schemas.enums import RiskPolicy
from app.tools.base import ToolRequest
from app.tools.git import GitTool
from app.tools.shell import ShellTool


class WorkerResult(BaseModel):
    task_id: str
    step_id: str
    worker_id: str
    status: str
    summary: str
    artifacts: list[ArtifactRecord] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    commands: list[list[str]] = Field(default_factory=list)
    validation_results: list[ValidationResultRecord] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    recommended_next_action: str | None = None


class Worker:
    def __init__(self, worker_id: str, workspace: str | Path) -> None:
        self.worker_id = worker_id
        self.workspace = Path(workspace).resolve()

    async def run_step(
        self,
        task_id: str,
        step_id: str,
        title: str,
        allowed_tools: list[str],
        command: list[str],
    ) -> WorkerResult:
        tool_name = self._tool_name(command)
        if tool_name not in allowed_tools:
            return self._blocked(task_id, step_id, title, command, f"tool '{tool_name}' is not allowed")

        if tool_name == "shell" and command[0] != "echo":
            return self._blocked(task_id, step_id, title, command, "only shell echo is supported")
        if tool_name == "git" and command != ["git", "status"]:
            return self._blocked(task_id, step_id, title, command, "only git status is supported")

        request = ToolRequest(
            command=command,
            working_dir=self.workspace,
            risk_policy=RiskPolicy.READ_ONLY,
        )
        adapter = (
            GitTool(workspace=self.workspace)
            if tool_name == "git"
            else ShellTool(allowlist={"echo"}, workspace=self.workspace)
        )
        try:
            result = await adapter.execute(request)
        except Exception as exc:
            return WorkerResult(
                task_id=task_id,
                step_id=step_id,
                worker_id=self.worker_id,
                status="failed",
                summary=f"{title} failed before completion.",
                commands=[command],
                validation_results=[
                    ValidationResultRecord(
                        check_name="tool_execution",
                        passed=False,
                        message=str(exc),
                    )
                ],
                errors=[str(exc)],
                recommended_next_action="correct_and_retry",
            )

        passed = result.exit_code == 0 and not result.timed_out
        return WorkerResult(
            task_id=task_id,
            step_id=step_id,
            worker_id=self.worker_id,
            status="succeeded" if passed else "failed",
            summary=f"{title} {'succeeded' if passed else 'failed'} with exit code {result.exit_code}.",
            evidence=[result.stdout] if result.stdout else [],
            commands=[command],
            validation_results=[
                ValidationResultRecord(
                    check_name="tool_execution",
                    passed=passed,
                    message=result.stderr or result.stdout or None,
                )
            ],
            errors=[] if passed else [result.stderr or f"exit code {result.exit_code}"],
            recommended_next_action="audit_result" if passed else "correct_and_retry",
        )

    def _tool_name(self, command: list[str]) -> str:
        if command and command[0] == "git":
            return "git"
        return "shell"

    def _blocked(
        self,
        task_id: str,
        step_id: str,
        title: str,
        command: list[str],
        error: str,
    ) -> WorkerResult:
        return WorkerResult(
            task_id=task_id,
            step_id=step_id,
            worker_id=self.worker_id,
            status="blocked",
            summary=f"{title} was blocked.",
            commands=[command],
            validation_results=[
                ValidationResultRecord(
                    check_name="tool_allowed",
                    passed=False,
                    message=error,
                )
            ],
            errors=[error],
            recommended_next_action="request_allowed_tool_or_change_step",
        )
