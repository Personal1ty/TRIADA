import asyncio
from datetime import UTC, datetime

import pytest
import shutil

from app.agents.auditor import Auditor
from app.agents.orchestrator import Orchestrator
from app.agents.worker import Worker
from app.audit.validator import audit_claims, audit_tool_results
from app.events.models import ArtifactRecord, ToolExecutionRecord
from app.llm.fake import FakeLLMProvider
from app.schemas.enums import AuditVerdictValue
from app.tools.base import ToolResult


def tool_result(command, exit_code=0, stdout="", stderr="", tool="shell"):
    now = datetime.now(UTC)
    return ToolResult(
        tool=tool,
        command=command,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        started_at=now,
        finished_at=now,
    )


class ProviderWithShellStep:
    async def complete_json(self, prompt: str, *, schema_name: str):
        return {
            "answer": {
                "steps": [
                    {
                        "id": "step-1",
                        "title": "Unsafe widened step",
                        "description": "Provider asks for shell",
                        "allowed_tools": ["shell"],
                    }
                ]
            }
        }


class ProviderWithNumericStepId:
    async def complete_json(self, prompt: str, *, schema_name: str):
        return {
            "answer": {
                "steps": [
                    {
                        "id": 1,
                        "title": "Inspect files",
                        "description": "Find repository files",
                        "allowed_tools": ["rg"],
                        "command": ["rg", "--files"],
                    }
                ]
            }
        }


class RecordingProvider:
    def __init__(self) -> None:
        self.calls = []

    async def complete_json(self, prompt: str, *, schema_name: str):
        self.calls.append({"prompt": prompt, "schema_name": schema_name})
        return {
            "thinking_summary_delta": {
                "stage": "execution",
                "action": "prepare_worker_step",
                "summary": "Worker model prepared the step.",
                "observations": ["tool evidence will decide outcome"],
                "next_step": "run_tool",
                "confidence": 0.7,
            },
            "answer": {"status": "ready"},
            "model_message": {"has_reasoning_content": True},
        }


class TransientRateLimitProvider(RecordingProvider):
    def __init__(self) -> None:
        super().__init__()
        self.attempts = 0

    async def complete_json(self, prompt: str, *, schema_name: str):
        self.attempts += 1
        if self.attempts == 1:
            raise RuntimeError("429 Too Many Requests")
        return await super().complete_json(prompt, schema_name=schema_name)


class StringSummaryProvider:
    async def complete_json(self, prompt: str, *, schema_name: str):
        return {
            "thinking_summary_delta": "Executed echo command to confirm FixMost corp-coder connected.",
            "answer": {"status": "ready"},
        }


class HangingWorkerProvider:
    async def complete_json(self, prompt: str, *, schema_name: str):
        await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_orchestrator_builds_plan_with_steps_and_required_checks():
    plan = await Orchestrator(FakeLLMProvider()).plan_task(
        goal="Check repository status",
        allowed_tools=["git"],
        acceptance_criteria=["git status was inspected"],
    )

    assert plan.steps
    assert plan.output_contract.required_checks == ["git status was inspected"]
    assert plan.steps[0].allowed_tools == ["git"]


@pytest.mark.asyncio
async def test_orchestrator_does_not_widen_provider_tools_beyond_allowlist():
    plan = await Orchestrator(ProviderWithShellStep()).plan_task(
        goal="Check repository status",
        allowed_tools=["git"],
        acceptance_criteria=["git status was inspected"],
    )

    assert plan.steps[0].allowed_tools == ["git"]
    assert "shell" not in plan.steps[0].allowed_tools


@pytest.mark.asyncio
async def test_orchestrator_normalizes_numeric_provider_step_id():
    plan = await Orchestrator(ProviderWithNumericStepId()).plan_task(
        goal="Inspect repository",
        allowed_tools=["rg"],
        acceptance_criteria=["files were inspected"],
    )

    assert plan.steps[0].id == "1"
    assert plan.steps[0].command == ["rg", "--files"]


@pytest.mark.asyncio
async def test_orchestrator_normalizes_string_model_summary_delta():
    plan = await Orchestrator(StringSummaryProvider()).plan_task(
        goal="Check repository status",
        allowed_tools=["git"],
        acceptance_criteria=["git status was inspected"],
    )

    assert plan.model_thinking_summary_delta["summary"] == (
        "Executed echo command to confirm FixMost corp-coder connected."
    )
    assert plan.model_thinking_summary_delta["stage"] == "planning"
    assert plan.model_thinking_summary_delta["action"] == "plan_task"


@pytest.mark.asyncio
async def test_orchestrator_classifies_destructive_goal_as_approval_required():
    plan = await Orchestrator(FakeLLMProvider()).plan_task(
        goal="Delete the production namespace and wipe all data",
        allowed_tools=["shell"],
        acceptance_criteria=["data removal approved"],
    )

    assert plan.risk_policy == "destructive"
    assert plan.requires_approval is True


@pytest.mark.asyncio
async def test_worker_runs_only_requested_echo_step(tmp_path):
    result = await Worker(worker_id="worker-1", workspace=tmp_path).run_step(
        task_id="task-1",
        step_id="step-2",
        title="Echo current step",
        allowed_tools=["shell"],
        command=["echo", "only step 2"],
    )

    assert result.task_id == "task-1"
    assert result.step_id == "step-2"
    assert result.worker_id == "worker-1"
    assert result.status == "succeeded"
    assert result.commands == [["echo", "only step 2"]]
    assert result.evidence == ["only step 2\n"]


@pytest.mark.asyncio
async def test_worker_supports_git_status_when_git_tool_allowed(tmp_path):
    result = await Worker(worker_id="worker-1", workspace=tmp_path).run_step(
        task_id="task-1",
        step_id="step-1",
        title="Inspect git status",
        allowed_tools=["git"],
        command=["git", "status"],
    )

    assert result.status in {"succeeded", "failed"}
    assert result.commands == [["git", "status"]]
    assert result.validation_results


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "command", "fixture_file"),
    [
        ("ls", ["ls"], None),
        ("cat", ["cat", "note.txt"], "note.txt"),
        ("sed", ["sed", "-n", "1p", "note.txt"], "note.txt"),
        ("rg", ["rg", "hello", "note.txt"], "note.txt"),
    ],
)
async def test_worker_supports_safe_read_only_tools(tmp_path, tool_name, command, fixture_file):
    if shutil.which(command[0]) is None:
        pytest.skip(f"{command[0]} is not installed")
    if fixture_file is not None:
        (tmp_path / fixture_file).write_text("hello\n")

    result = await Worker(worker_id="worker-1", workspace=tmp_path).run_step(
        task_id="task-1",
        step_id="step-1",
        title=f"Run {tool_name}",
        allowed_tools=[tool_name],
        command=command,
    )

    assert result.status == "succeeded"
    assert result.commands == [command]


@pytest.mark.asyncio
async def test_worker_supports_pytest_as_safe_read_only_tool(tmp_path):
    if shutil.which("pytest") is None:
        pytest.skip("pytest is not installed")
    test_file = tmp_path / "test_sample.py"
    test_file.write_text("def test_sample():\n    assert True\n")

    result = await Worker(worker_id="worker-1", workspace=tmp_path).run_step(
        task_id="task-1",
        step_id="step-1",
        title="Run pytest",
        allowed_tools=["pytest"],
        command=["pytest", "-q", "test_sample.py"],
    )

    assert result.status == "succeeded"
    assert result.commands == [["pytest", "-q", "test_sample.py"]]


@pytest.mark.asyncio
async def test_worker_blocks_mutating_sed_flag(tmp_path):
    note = tmp_path / "note.txt"
    note.write_text("hello\n")

    result = await Worker(worker_id="worker-1", workspace=tmp_path).run_step(
        task_id="task-1",
        step_id="step-1",
        title="Mutate with sed",
        allowed_tools=["sed"],
        command=["sed", "-i", "s/hello/bye/", "note.txt"],
    )

    assert result.status == "blocked"
    assert "not supported as a safe read-only command" in result.errors[0]
    assert note.read_text() == "hello\n"


@pytest.mark.asyncio
async def test_worker_blocks_sed_in_place_suffix(tmp_path):
    note = tmp_path / "note.txt"
    note.write_text("hello\n")

    result = await Worker(worker_id="worker-1", workspace=tmp_path).run_step(
        task_id="task-1",
        step_id="step-1",
        title="Mutate with sed suffix",
        allowed_tools=["sed"],
        command=["sed", "-i.tmp", "s/hello/bye/", "note.txt"],
    )

    assert result.status == "blocked"
    assert "not supported as a safe read-only command" in result.errors[0]
    assert note.read_text() == "hello\n"


@pytest.mark.asyncio
async def test_worker_blocks_symlink_read_outside_workspace(tmp_path):
    outside = tmp_path.parent / "outside-secret.txt"
    outside.write_text("secret\n")
    link = tmp_path / "link.txt"
    link.symlink_to(outside)

    result = await Worker(worker_id="worker-1", workspace=tmp_path).run_step(
        task_id="task-1",
        step_id="step-1",
        title="Read symlink",
        allowed_tools=["cat"],
        command=["cat", "link.txt"],
    )

    assert result.status == "blocked"
    assert "not supported as a safe read-only command" in result.errors[0]


@pytest.mark.asyncio
async def test_worker_rejects_disallowed_tool(tmp_path):
    result = await Worker(worker_id="worker-1", workspace=tmp_path).run_step(
        task_id="task-1",
        step_id="step-1",
        title="Run echo without shell permission",
        allowed_tools=["git"],
        command=["echo", "not allowed"],
    )

    assert result.status == "blocked"
    assert result.errors == ["tool 'echo' is not allowed"]


@pytest.mark.asyncio
async def test_worker_blocks_empty_command(tmp_path):
    result = await Worker(worker_id="worker-1", workspace=tmp_path).run_step(
        task_id="task-1",
        step_id="step-1",
        title="Run empty command",
        allowed_tools=["shell"],
        command=[],
    )

    assert result.status == "blocked"
    assert result.errors == ["command is required"]
    assert result.validation_results[0].check_name == "command_required"


@pytest.mark.asyncio
async def test_worker_calls_model_and_returns_public_model_summary(tmp_path):
    provider = RecordingProvider()

    result = await Worker(worker_id="worker-1", workspace=tmp_path, llm=provider).run_step(
        task_id="task-1",
        step_id="step-1",
        title="Echo current step",
        allowed_tools=["shell"],
        command=["echo", "hello"],
    )

    assert result.status == "succeeded"
    assert provider.calls
    assert provider.calls[0]["schema_name"] == "worker_result"
    assert result.model_thinking_summary_delta["summary"] == "Worker model prepared the step."
    assert result.model_message["has_reasoning_content"] is True


@pytest.mark.asyncio
async def test_worker_normalizes_string_model_summary_delta(tmp_path):
    result = await Worker(worker_id="worker-1", workspace=tmp_path, llm=StringSummaryProvider()).run_step(
        task_id="task-1",
        step_id="step-1",
        title="Echo current step",
        allowed_tools=["echo"],
        command=["echo", "hello"],
    )

    assert result.status == "succeeded"
    assert result.model_thinking_summary_delta["summary"] == (
        "Executed echo command to confirm FixMost corp-coder connected."
    )
    assert result.model_thinking_summary_delta["stage"] == "execution"


@pytest.mark.asyncio
async def test_worker_fails_when_model_preparation_times_out(tmp_path):
    result = await Worker(
        worker_id="worker-1",
        workspace=tmp_path,
        llm=HangingWorkerProvider(),
        llm_timeout_seconds=0.01,
    ).run_step(
        task_id="task-1",
        step_id="step-1",
        title="Echo current step",
        allowed_tools=["echo"],
        command=["echo", "hello"],
    )

    assert result.status == "failed"
    assert result.validation_results[0].check_name == "llm_prepare_timeout"
    assert "timed out after 0.01 seconds" in result.errors[0]
    assert result.tool_results == []


@pytest.mark.asyncio
async def test_worker_retries_transient_rate_limit_before_running_tool(tmp_path):
    provider = TransientRateLimitProvider()
    result = await Worker(worker_id="worker-1", workspace=tmp_path, llm=provider).run_step(
        task_id="task-1",
        step_id="step-1",
        title="Echo current step",
        allowed_tools=["echo"],
        command=["echo", "hello"],
    )

    assert result.status == "succeeded"
    assert provider.attempts == 2


@pytest.mark.asyncio
async def test_worker_blocks_write_file_outside_workspace(tmp_path):
    result = await Worker(worker_id="worker-1", workspace=tmp_path).run_step(
        task_id="task-1",
        step_id="step-1",
        title="Write outside workspace",
        allowed_tools=["write_file"],
        command=["write_file", "../outside.txt", "unsafe"],
        risk_policy="high_risk_write",
        approval_ref="operator",
    )

    assert result.status == "blocked"
    assert "not supported as a safe read-only command" in result.errors[0]
    assert not (tmp_path.parent / "outside.txt").exists()


def test_auditor_reports_unmentioned_tool_failure():
    verdict = audit_tool_results(
        [tool_result(["echo", "boom"], exit_code=1, stderr="boom")],
        worker_summary="Completed the step successfully.",
    )

    assert verdict.verdict == AuditVerdictValue.CORRECTIONS_REQUIRED
    assert [violation.rule_id for violation in verdict.violations] == [
        "TOOL_FAILURE_NOT_REPORTED"
    ]


def test_auditor_accepts_tool_execution_record_failure():
    verdict = Auditor().audit_tool_results(
        [
            ToolExecutionRecord(
                tool="shell",
                command=["false"],
                exit_code=1,
                stdout_ref=None,
                stderr_ref=None,
                started_at=None,
                finished_at=None,
                timed_out=False,
            )
        ],
        worker_summary="Completed the step successfully.",
    )

    assert verdict.verdict == AuditVerdictValue.CORRECTIONS_REQUIRED
    assert verdict.violations[0].rule_id == "TOOL_FAILURE_NOT_REPORTED"


def test_auditor_allows_reported_tool_failure():
    verdict = Auditor().audit_tool_results(
        [tool_result(["echo", "boom"], exit_code=1, stderr="boom")],
        worker_summary="Command failed with exit code 1: boom",
    )

    assert verdict.verdict == AuditVerdictValue.PASS
    assert verdict.violations == []


def test_auditor_flags_contradictory_failure_and_success_summary():
    verdict = audit_tool_results(
        [tool_result(["false"], exit_code=1, stderr="failed")],
        worker_summary="Command failed with exit code 1, but the task succeeded.",
    )

    assert verdict.verdict == AuditVerdictValue.CORRECTIONS_REQUIRED
    assert verdict.violations[0].rule_id == "SUMMARY_CONTRADICTS_TOOL_RESULT"


def test_auditor_reports_required_artifact_missing():
    verdict = audit_claims(
        required_artifacts=["report.json"],
        artifacts=[ArtifactRecord(name="summary.txt", artifact_type="text")],
        thinking_deltas=[],
    )

    assert verdict.verdict == "corrections_required"
    assert [violation.rule_id for violation in verdict.violations] == [
        "REQUIRED_ARTIFACT_MISSING"
    ]


def test_auditor_does_not_treat_thinking_deltas_as_artifact_evidence():
    verdict = Auditor().audit_claims(
        required_artifacts=["report.json"],
        artifacts=[],
        thinking_deltas=[{"summary": "I produced report.json"}],
    )

    assert verdict.verdict == AuditVerdictValue.CORRECTIONS_REQUIRED
    assert verdict.violations[0].rule_id == "REQUIRED_ARTIFACT_MISSING"


def test_auditor_detects_success_claim_without_evidence():
    verdict = audit_tool_results([], worker_summary="Successfully completed the task.")

    assert verdict.verdict == AuditVerdictValue.CORRECTIONS_REQUIRED
    assert [violation.rule_id for violation in verdict.violations] == [
        "SUCCESS_CLAIM_WITHOUT_EVIDENCE"
    ]
