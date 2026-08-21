from __future__ import annotations

import asyncio
from pathlib import Path
import shutil

from pydantic import BaseModel, Field

from app.events.models import ArtifactRecord, ToolExecutionRecord, ValidationResultRecord
from app.contracts.capabilities import check_capability
from app.schemas.enums import RiskPolicy
from app.tools.apply_patch import ApplyPatchTool
from app.tools.base import ToolRequest
from app.tools.git import GitTool
from app.tools.shell import ShellTool
from app.tools.write_file import WriteFileTool

_SAFE_READ_ONLY_TOOLS = {"echo", "pytest", "rg", "ls", "cat", "sed"}
_WRITE_TOOLS = {"write_file", "apply_patch"}
_WRITE_SHELL_TOOLS = {"mkdir", "touch"}
_SAFE_SHELL_ALLOWLIST = _SAFE_READ_ONLY_TOOLS | _WRITE_SHELL_TOOLS
_MUTATING_TOOL_ARGS = {
    "sed": {"--in-place"},
    "pytest": {"--cache-clear", "--junitxml", "--basetemp", "--result-log"},
}
_PYTEST_MUTATING_PREFIXES = ("--junitxml=", "--basetemp=", "--result-log=")


class WorkerResult(BaseModel):
    task_id: str
    step_id: str
    worker_id: str
    status: str
    summary: str
    artifacts: list[ArtifactRecord] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    commands: list[list[str]] = Field(default_factory=list)
    tool_results: list[ToolExecutionRecord] = Field(default_factory=list)
    validation_results: list[ValidationResultRecord] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    recommended_next_action: str | None = None
    model_thinking_summary_delta: dict | None = None
    model_message: dict = Field(default_factory=dict)
    raw_reasoning_content: str | None = Field(default=None, exclude=True)


class Worker:
    def __init__(
        self,
        worker_id: str,
        workspace: str | Path,
        llm=None,
        role: str = "worker",
        llm_timeout_seconds: float = 60.0,
    ) -> None:
        self.worker_id = worker_id
        self.workspace = Path(workspace).resolve()
        self.llm = llm
        self.role = role
        self.llm_timeout_seconds = llm_timeout_seconds

    async def run_step(
        self,
        task_id: str,
        step_id: str,
        title: str,
        allowed_tools: list[str],
        command: list[str],
        risk_policy: RiskPolicy = RiskPolicy.READ_ONLY,
        approval_ref: str | None = None,
    ) -> WorkerResult:
        if not command:
            return self._blocked(
                task_id,
                step_id,
                title,
                command,
                "command is required",
                check_name="command_required",
            )
        capability = check_capability(self.role, "execute_tools")
        if not capability["allowed"]:
            return self._blocked(task_id, step_id, title, command, capability["reason"] or "capability denied")
        tool_name = self._tool_name(command)
        if not self._is_tool_allowed(tool_name, allowed_tools):
            return self._blocked(task_id, step_id, title, command, f"tool '{tool_name}' is not allowed")

        if not self._is_supported_safe_command(tool_name, command, risk_policy, approval_ref):
            return self._blocked(
                task_id,
                step_id,
                title,
                command,
                f"{' '.join(command)} is not supported as a safe read-only command",
            )

        try:
            model_response = await asyncio.wait_for(
                self._prepare_with_model(
                    task_id=task_id,
                    step_id=step_id,
                    title=title,
                    allowed_tools=allowed_tools,
                    command=command,
                    risk_policy=risk_policy,
                ),
                timeout=self.llm_timeout_seconds,
            )
        except TimeoutError:
            return self._failed_before_tool(
                task_id,
                step_id,
                title,
                command,
                f"LLM preparation timed out after {self.llm_timeout_seconds:g} seconds",
                check_name="llm_prepare_timeout",
            )
        except Exception as exc:
            if "429" in str(exc):
                model_response = {}
            else:
                return self._failed_before_tool(
                    task_id,
                    step_id,
                    title,
                    command,
                    f"LLM preparation failed: {exc}",
                    check_name="llm_prepare",
                )
        request = ToolRequest(
            command=command,
            working_dir=self.workspace,
            risk_policy=risk_policy,
            approval_ref=approval_ref,
        )
        adapter = self._adapter_for_tool(tool_name)
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
                model_thinking_summary_delta=self._model_summary_delta(model_response),
                model_message=model_response.get("model_message", {}),
                raw_reasoning_content=model_response.get("raw_reasoning_content"),
            )

        passed = result.exit_code == 0 and not result.timed_out
        tool_record = ToolExecutionRecord(
            tool=result.tool,
            command=result.command,
            risk_policy=risk_policy.value,
            exit_code=result.exit_code,
            started_at=result.started_at,
            finished_at=result.finished_at,
            timed_out=result.timed_out,
            metadata=result.metadata,
        )
        return WorkerResult(
            task_id=task_id,
            step_id=step_id,
            worker_id=self.worker_id,
            status="succeeded" if passed else "failed",
            summary=f"{title} {'succeeded' if passed else 'failed'} with exit code {result.exit_code}.",
            evidence=[result.stdout] if result.stdout else [],
            commands=[command],
            tool_results=[tool_record],
            validation_results=[
                ValidationResultRecord(
                    check_name="tool_execution",
                    passed=passed,
                    message=result.stderr or result.stdout or None,
                )
            ],
            errors=[] if passed else [result.stderr or f"exit code {result.exit_code}"],
            recommended_next_action="audit_result" if passed else "correct_and_retry",
            model_thinking_summary_delta=self._model_summary_delta(model_response),
            model_message=model_response.get("model_message", {}),
            raw_reasoning_content=model_response.get("raw_reasoning_content"),
        )

    def _model_summary_delta(self, model_response: dict) -> dict | None:
        value = model_response.get("thinking_summary_delta")
        if isinstance(value, dict):
            return value
        if isinstance(value, str) and value.strip():
            return {
                "stage": "execution",
                "action": "prepare_worker_step",
                "summary": value.strip(),
                "observations": [],
                "next_step": "run_tool",
                "confidence": None,
            }
        return None

    def _tool_name(self, command: list[str]) -> str:
        if command and command[0] == "git":
            return "git"
        if command and command[0] in _SAFE_READ_ONLY_TOOLS | _WRITE_TOOLS | _WRITE_SHELL_TOOLS:
            return command[0]
        return "shell"

    def _is_tool_allowed(self, tool_name: str, allowed_tools: list[str]) -> bool:
        if tool_name in allowed_tools:
            return True
        return tool_name == "echo" and "shell" in allowed_tools

    def _is_supported_safe_command(
        self,
        tool_name: str,
        command: list[str],
        risk_policy: RiskPolicy,
        approval_ref: str | None,
    ) -> bool:
        if tool_name == "git":
            return GitTool(workspace=self.workspace).is_command_allowed(
                command,
                risk_policy=risk_policy,
                approval_ref=approval_ref,
            )
        if tool_name in _WRITE_TOOLS:
            return self._write_command_stays_in_workspace(command)
        if tool_name in _WRITE_SHELL_TOOLS:
            return self._write_shell_command_stays_in_workspace(command)
        if tool_name not in _SAFE_READ_ONLY_TOOLS:
            return False
        if self._has_mutating_arg(tool_name, command):
            return False
        return self._path_args_stay_in_workspace(command)

    def _adapter_for_tool(self, tool_name: str):
        if tool_name == "git":
            return GitTool(workspace=self.workspace)
        if tool_name == "apply_patch":
            return ApplyPatchTool(workspace=self.workspace)
        if tool_name == "write_file":
            return WriteFileTool(workspace=self.workspace)
        executable = shutil.which(tool_name)
        trusted_paths = [Path(executable).parent] if executable else None
        return ShellTool(
            allowlist=_SAFE_SHELL_ALLOWLIST,
            workspace=self.workspace,
            trusted_paths=trusted_paths,
        )

    def _has_mutating_arg(self, tool_name: str, command: list[str]) -> bool:
        blocked_args = _MUTATING_TOOL_ARGS.get(tool_name, set())
        for arg in command[1:]:
            if tool_name == "sed" and (arg == "-i" or arg.startswith("-i")):
                return True
            if tool_name == "pytest" and arg.startswith(_PYTEST_MUTATING_PREFIXES):
                return True
            if arg in blocked_args or any(arg.startswith(f"{blocked}=") for blocked in blocked_args):
                return True
        return False

    def _write_command_stays_in_workspace(self, command: list[str]) -> bool:
        if command[0] == "write_file" and len(command) != 3:
            return False
        if command[0] == "apply_patch" and len(command) != 4:
            return False
        if command[0] not in _WRITE_TOOLS:
            return False
        return self._relative_path_stays_in_workspace(command[1])

    def _write_shell_command_stays_in_workspace(self, command: list[str]) -> bool:
        if not command or command[0] not in _WRITE_SHELL_TOOLS:
            return False
        if command[0] == "mkdir":
            path_args = [arg for arg in command[1:] if arg != "-p"]
            if len(path_args) != len(command[1:]) - command[1:].count("-p"):
                return False
            return bool(path_args) and all(self._relative_path_stays_in_workspace(arg) for arg in path_args)
        if command[0] == "touch":
            return len(command) >= 2 and all(
                not arg.startswith("-") and self._relative_path_stays_in_workspace(arg)
                for arg in command[1:]
            )
        return False

    def _relative_path_stays_in_workspace(self, raw_path: str) -> bool:
        path = Path(raw_path)
        if path.is_absolute() or any(part == ".." for part in path.parts):
            return False
        candidate = (self.workspace / path).resolve()
        return candidate != self.workspace and candidate.is_relative_to(self.workspace)

    def _path_args_stay_in_workspace(self, command: list[str]) -> bool:
        skip_next = False
        for index, arg in enumerate(command[1:], start=1):
            if skip_next:
                skip_next = False
                continue
            if command[0] == "sed" and index == 1 and (arg.startswith("s/") or arg.endswith("p")):
                continue
            if arg.startswith("-"):
                if command[0] == "pytest" and arg in _MUTATING_TOOL_ARGS["pytest"]:
                    skip_next = True
                continue
            if command[0] == "sed" and (arg.startswith("s/") or arg.endswith("p")):
                continue
            path = Path(arg)
            candidate = path if path.is_absolute() else self.workspace / path
            if path.parts and (candidate.exists() or path.is_absolute() or any(part == ".." for part in path.parts)):
                resolved = candidate.resolve()
                if resolved != self.workspace and not resolved.is_relative_to(self.workspace):
                    return False
        return True

    async def _prepare_with_model(
        self,
        *,
        task_id: str,
        step_id: str,
        title: str,
        allowed_tools: list[str],
        command: list[str],
        risk_policy: RiskPolicy,
    ) -> dict:
        if self.llm is None or not hasattr(self.llm, "complete_json"):
            return {}
        prompt = "\n".join(
            [
                f"Task id: {task_id}",
                f"Step id: {step_id}",
                f"Title: {title}",
                f"Allowed tools: {', '.join(allowed_tools)}",
                f"Command: {' '.join(command)}",
                f"Risk policy: {risk_policy.value}",
                "Return JSON with a public thinking_summary_delta and answer.",
            ]
        )
        response = None
        for attempt in range(3):
            try:
                response = await self.llm.complete_json(prompt, schema_name="worker_result")
                break
            except Exception as exc:
                if "429" not in str(exc) or attempt == 2:
                    raise
                await asyncio.sleep(0.05 * (attempt + 1))
        return response if isinstance(response, dict) else {}

    def _blocked(
        self,
        task_id: str,
        step_id: str,
        title: str,
        command: list[str],
        error: str,
        check_name: str = "tool_allowed",
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
                    check_name=check_name,
                    passed=False,
                    message=error,
                )
            ],
            errors=[error],
            recommended_next_action="request_allowed_tool_or_change_step",
        )

    def _failed_before_tool(
        self,
        task_id: str,
        step_id: str,
        title: str,
        command: list[str],
        error: str,
        *,
        check_name: str,
    ) -> WorkerResult:
        return WorkerResult(
            task_id=task_id,
            step_id=step_id,
            worker_id=self.worker_id,
            status="failed",
            summary=f"{title} failed before tool execution.",
            commands=[command],
            validation_results=[
                ValidationResultRecord(
                    check_name=check_name,
                    passed=False,
                    message=error,
                )
            ],
            errors=[error],
            recommended_next_action="retry_with_bounded_llm_request",
        )
