from __future__ import annotations

from uuid import uuid4

import pytest

from app.agents.orchestrator import Orchestrator
from app.config import get_settings
from app.llm.codex_bridge import CodexBridgeProvider
from app.llm.runtime_config import LLMConfigService, LLMProviderConfig
from app.llm.openai_compatible import OpenAICompatibleProvider
from app.llm.openai_responses import OpenAIResponsesProvider
from app.schemas.enums import AgentRole
from app.services.execution_engine import ExecutionEngine
from app.services.task_service import TaskRecord, TaskService


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class MemoryEmitter:
    def __init__(self) -> None:
        self.events = []

    async def emit(self, **kwargs):
        self.events.append(kwargs)


class UnavailableLLM:
    async def complete_json(self, prompt: str, *, schema_name: str):
        raise RuntimeError("connection refused")


class AgentSummaryLLM:
    async def complete_json(self, prompt: str, *, schema_name: str):
        summaries = {
            "plan": {
                "stage": "planning",
                "action": "draft_plan",
                "summary": "Orchestrator model planned one safe step.",
                "observations": ["read-only command selected"],
                "next_step": "dispatch_worker",
                "confidence": 0.9,
            },
            "worker_result": {
                "stage": "execution",
                "action": "prepare_worker_step",
                "summary": "Worker model prepared tool execution.",
                "observations": ["echo is allowed"],
                "next_step": "run_tool",
                "confidence": 0.8,
            },
            "audit_verdict": {
                "stage": "audit",
                "action": "evaluate_evidence",
                "summary": "Auditor model reviewed worker evidence.",
                "observations": ["tool result was available"],
                "next_step": "return_verdict",
                "confidence": 0.85,
            },
        }
        answers = {
            "plan": {
                "steps": [
                    {
                        "id": "step-1",
                        "title": "Echo",
                        "description": "hello",
                        "allowed_tools": ["shell"],
                    }
                ]
            },
            "worker_result": {"status": "ready"},
            "audit_verdict": {"approved": True},
        }
        return {
            "thinking_summary_delta": summaries[schema_name],
            "answer": answers[schema_name],
            "model_message": {"has_reasoning_content": True},
            "raw_reasoning_content": f"raw {schema_name} reasoning",
        }


class MultiStepLLM:
    async def complete_json(self, prompt: str, *, schema_name: str):
        if schema_name == "plan":
            return {
                "answer": {
                    "steps": [
                        {
                            "id": "step-1",
                            "title": "List files",
                            "description": "List repository files",
                            "allowed_tools": ["ls"],
                            "command": ["ls"],
                        },
                        {
                            "id": "step-2",
                            "title": "Read README",
                            "description": "Read the README header",
                            "allowed_tools": ["sed"],
                            "command": ["sed", "-n", "1,5p", "README.md"],
                        },
                    ]
                }
            }
        if schema_name == "worker_result":
            return {"answer": {"status": "ready"}}
        if schema_name == "audit_verdict":
            return {"answer": {"approved": True}}
        return {}


class WriteFileLLM:
    async def complete_json(self, prompt: str, *, schema_name: str):
        if schema_name == "plan":
            return {
                "answer": {
                    "steps": [
                        {
                            "id": "step-1",
                            "title": "Write marker",
                            "description": "Write an approved marker file",
                            "allowed_tools": ["write_file"],
                            "command": ["write_file", "triada-marker.txt", "approved marker\n"],
                        }
                    ]
                }
            }
        if schema_name == "worker_result":
            return {"answer": {"status": "ready"}}
        if schema_name == "audit_verdict":
            return {"answer": {"approved": True}}
        return {}


class WriteFileThenUnavailableLLM:
    def __init__(self) -> None:
        self.plan_calls = 0

    async def complete_json(self, prompt: str, *, schema_name: str):
        if schema_name == "plan":
            self.plan_calls += 1
            if self.plan_calls > 1:
                raise RuntimeError("planner should not be called after approval")
            return {
                "answer": {
                    "steps": [
                        {
                            "id": "step-1",
                            "title": "Write marker",
                            "description": "Write an approved marker file",
                            "allowed_tools": ["write_file"],
                            "command": ["write_file", "triada-marker.txt", "approved marker\n"],
                        }
                    ]
                }
            }
        if schema_name == "worker_result":
            return {"answer": {"status": "ready"}}
        if schema_name == "audit_verdict":
            return {"answer": {"approved": True}}
        return {}


class PatchFileLLM:
    async def complete_json(self, prompt: str, *, schema_name: str):
        if schema_name == "plan":
            return {
                "answer": {
                    "steps": [
                        {
                            "id": "step-1",
                            "title": "Patch README",
                            "description": "Patch an existing file after approval",
                            "allowed_tools": ["apply_patch"],
                            "command": ["apply_patch", "README.md", "old heading", "new heading"],
                        }
                    ]
                }
            }
        if schema_name == "worker_result":
            return {"answer": {"status": "ready"}}
        if schema_name == "audit_verdict":
            return {"answer": {"approved": True}}
        return {}


class ShellWriteLLM:
    async def complete_json(self, prompt: str, *, schema_name: str):
        if schema_name == "plan":
            return {
                "answer": {
                    "steps": [
                        {
                            "id": "step-1",
                            "title": "Create output directory",
                            "description": "Create an approved workspace directory",
                            "allowed_tools": ["mkdir"],
                            "command": ["mkdir", "-p", "triada-output"],
                        }
                    ]
                }
            }
        if schema_name == "worker_result":
            return {"answer": {"status": "ready"}}
        if schema_name == "audit_verdict":
            return {"answer": {"approved": True}}
        return {}


def make_task(*, goal: str, allowed_tools: list[str] | None = None) -> TaskRecord:
    return TaskRecord(
        id=uuid4(),
        trace_id=uuid4(),
        goal=goal,
        allowed_tools=allowed_tools or ["shell"],
        acceptance_criteria=["task handled"],
    )


@pytest.mark.asyncio
async def test_execution_engine_normalizes_string_model_delta(tmp_path):
    emitter = MemoryEmitter()
    engine = ExecutionEngine(emitter=emitter, workspace=tmp_path)
    task = make_task(goal="Echo")

    await engine._emit_model_delta(
        task,
        agent_id="auditor-1",
        agent_role=AgentRole.AUDITOR,
        delta="Auditor reviewed the evidence and approved it.",
    )

    event = emitter.events[0]
    assert event["event_type"] == "thinking_summary_delta"
    assert event["payload"]["summary"] == "Auditor reviewed the evidence and approved it."
    assert event["payload"]["stage"] == "model"


def test_execution_engine_uses_openai_compatible_provider_from_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("LLM_MODEL", "corp-coder")
    get_settings.cache_clear()

    engine = ExecutionEngine(emitter=MemoryEmitter(), workspace=tmp_path)

    assert isinstance(engine._orchestrator.llm, OpenAICompatibleProvider)
    assert engine._orchestrator.llm.base_url == "http://127.0.0.1:11434/v1"
    assert engine._orchestrator.llm.model == "corp-coder"


def test_execution_engine_prefers_runtime_llm_config_over_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    get_settings.cache_clear()
    service = LLMConfigService(
        settings=get_settings(),
        config_path=tmp_path / "llm-config.enc",
        key_path=tmp_path / "llm-config.key",
    )
    service.save(
        LLMProviderConfig(
            provider="openai-compatible",
            base_url="https://runtime-llm.example/v1",
            model="runtime-model",
            api_key="sk-runtime-secret",
        )
    )

    engine = ExecutionEngine(
        emitter=MemoryEmitter(),
        workspace=tmp_path,
        llm_config_service=service,
    )

    assert isinstance(engine._orchestrator.llm, OpenAICompatibleProvider)
    assert engine._orchestrator.llm.base_url == "https://runtime-llm.example/v1"
    assert engine._orchestrator.llm.model == "runtime-model"
    assert engine._orchestrator.llm.api_key == "sk-runtime-secret"


def test_execution_engine_uses_openai_responses_provider_from_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_PROVIDER", "openai-responses")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.openai.test/v1")
    monkeypatch.setenv("LLM_API_KEY", "sk-secret-token")
    monkeypatch.setenv("LLM_MODEL", "gpt-test")
    get_settings.cache_clear()

    engine = ExecutionEngine(emitter=MemoryEmitter(), workspace=tmp_path)

    assert isinstance(engine._orchestrator.llm, OpenAIResponsesProvider)
    assert engine._orchestrator.llm.base_url == "https://api.openai.test/v1"
    assert engine._orchestrator.llm.model == "gpt-test"


def test_execution_engine_uses_codex_bridge_provider_from_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_PROVIDER", "codex-bridge")
    get_settings.cache_clear()

    engine = ExecutionEngine(emitter=MemoryEmitter(), workspace=tmp_path)

    assert isinstance(engine._orchestrator.llm, CodexBridgeProvider)


@pytest.mark.asyncio
async def test_execution_engine_blocks_and_emits_llm_unavailable_when_provider_fails(tmp_path):
    emitter = MemoryEmitter()
    engine = ExecutionEngine(
        emitter=emitter,
        workspace=tmp_path,
        orchestrator=Orchestrator(UnavailableLLM()),
    )
    task = make_task(goal="Inspect repository", allowed_tools=["git"])

    status = await engine.run_once(task)

    assert status == "blocked"
    event_types = [event["event_type"] for event in emitter.events]
    assert "llm_unavailable" in event_types
    assert "planning_completed" not in event_types
    unavailable = next(event for event in emitter.events if event["event_type"] == "llm_unavailable")
    assert unavailable["payload"]["status"] == "blocked"
    assert unavailable["payload"]["provider"] == "UnavailableLLM"


@pytest.mark.asyncio
async def test_read_only_ls_runs_without_approval(tmp_path):
    emitter = MemoryEmitter()
    engine = ExecutionEngine(emitter=emitter, workspace=tmp_path)
    task = make_task(goal="List workspace files", allowed_tools=["ls"])

    status = await engine.run_once(task)

    assert status == "completed"
    event_types = [event["event_type"] for event in emitter.events]
    assert "task_waiting_approval" not in event_types
    tool_events = [event for event in emitter.events if event["event_type"] == "tool_execution_completed"]
    assert tool_events
    assert tool_events[0]["payload"]["tool"] == "shell"
    assert tool_events[0]["payload"]["command"] == ["ls"]


@pytest.mark.asyncio
async def test_execution_engine_runs_multiple_model_planned_steps(tmp_path):
    (tmp_path / "README.md").write_text("# TRIADA\n\nLocal framework\n", encoding="utf-8")
    emitter = MemoryEmitter()
    llm = MultiStepLLM()
    engine = ExecutionEngine(
        emitter=emitter,
        workspace=tmp_path,
        orchestrator=Orchestrator(llm),
    )
    engine._auditor.llm = llm
    task = make_task(goal="Inspect repository structure", allowed_tools=["ls", "sed"])

    status = await engine.run_once(task)

    assert status == "completed"
    tool_events = [event for event in emitter.events if event["event_type"] == "tool_execution_completed"]
    assert [event["payload"]["command"] for event in tool_events] == [
        ["ls"],
        ["sed", "-n", "1,5p", "README.md"],
    ]
    assert [event["payload"]["exit_code"] for event in tool_events] == [0, 0]


@pytest.mark.asyncio
async def test_write_task_waits_for_approval_before_worker_execution(tmp_path):
    emitter = MemoryEmitter()
    service = TaskService(
        emitter=emitter,
        execution_engine=ExecutionEngine(emitter=emitter, workspace=tmp_path),
    )
    task = await service.create_task(
        goal="write a deployment marker",
        allowed_tools=["shell"],
        acceptance_criteria=["change approved"],
    )

    waiting = await service.run_task_once(task.id)

    assert waiting.status == "waiting_approval"
    event_types = [event["event_type"] for event in emitter.events]
    assert "approval_required" in event_types
    assert "worker_step_started" not in event_types
    assert event_types[-1] == "task_waiting_approval"


@pytest.mark.asyncio
async def test_approved_write_task_can_continue_to_worker(tmp_path):
    emitter = MemoryEmitter()
    service = TaskService(
        emitter=emitter,
        execution_engine=ExecutionEngine(emitter=emitter, workspace=tmp_path),
    )
    task = await service.create_task(
        goal="write a deployment marker",
        allowed_tools=["shell"],
        acceptance_criteria=["change approved"],
    )
    await service.run_task_once(task.id)
    await service.approve_task(task.id, approved_by="operator")

    completed = await service.run_task_once(task.id)

    assert completed.status == "completed"
    event_types = [event["event_type"] for event in emitter.events]
    assert "task_approved" in event_types
    assert "worker_step_completed" in event_types


@pytest.mark.asyncio
async def test_approved_write_file_step_changes_workspace_file(tmp_path):
    emitter = MemoryEmitter()
    llm = WriteFileLLM()
    service = TaskService(
        emitter=emitter,
        execution_engine=ExecutionEngine(
            emitter=emitter,
            workspace=tmp_path,
            orchestrator=Orchestrator(llm),
        ),
    )
    service._execution_engine._auditor.llm = llm
    task = await service.create_task(
        goal="write approved marker file",
        allowed_tools=["write_file"],
        acceptance_criteria=["marker file exists after approval"],
    )

    waiting = await service.run_task_once(task.id)
    await service.approve_task(task.id, approved_by="operator")
    completed = await service.run_task_once(task.id)

    assert waiting.status == "waiting_approval"
    assert completed.status == "completed"
    assert (tmp_path / "triada-marker.txt").read_text(encoding="utf-8") == "approved marker\n"
    tool_events = [event for event in emitter.events if event["event_type"] == "tool_execution_completed"]
    assert tool_events[-1]["payload"]["tool"] == "write_file"
    assert tool_events[-1]["payload"]["command"] == ["write_file", "triada-marker.txt", "approved marker\n"]


@pytest.mark.asyncio
async def test_approved_write_task_reuses_pending_plan_without_replanning(tmp_path):
    emitter = MemoryEmitter()
    llm = WriteFileThenUnavailableLLM()
    service = TaskService(
        emitter=emitter,
        execution_engine=ExecutionEngine(
            emitter=emitter,
            workspace=tmp_path,
            orchestrator=Orchestrator(llm),
        ),
    )
    service._execution_engine._auditor.llm = llm
    task = await service.create_task(
        goal="write approved marker file",
        allowed_tools=["write_file"],
        acceptance_criteria=["marker file exists after approval"],
    )

    waiting = await service.run_task_once(task.id)
    await service.approve_task(task.id, approved_by="operator")
    completed = await service.run_task_once(task.id)

    assert waiting.status == "waiting_approval"
    assert completed.status == "completed"
    assert llm.plan_calls == 1
    assert (tmp_path / "triada-marker.txt").read_text(encoding="utf-8") == "approved marker\n"


@pytest.mark.asyncio
async def test_approved_apply_patch_step_changes_existing_workspace_file(tmp_path):
    (tmp_path / "README.md").write_text("old heading\nbody\n", encoding="utf-8")
    emitter = MemoryEmitter()
    llm = PatchFileLLM()
    service = TaskService(
        emitter=emitter,
        execution_engine=ExecutionEngine(
            emitter=emitter,
            workspace=tmp_path,
            orchestrator=Orchestrator(llm),
        ),
    )
    service._execution_engine._auditor.llm = llm
    task = await service.create_task(
        goal="write approved patch to README",
        allowed_tools=["apply_patch"],
        acceptance_criteria=["README heading is patched"],
    )

    waiting = await service.run_task_once(task.id)
    await service.approve_task(task.id, approved_by="operator")
    completed = await service.run_task_once(task.id)

    assert waiting.status == "waiting_approval"
    assert completed.status == "completed"
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == "new heading\nbody\n"
    tool_events = [event for event in emitter.events if event["event_type"] == "tool_execution_completed"]
    assert tool_events[-1]["payload"]["tool"] == "apply_patch"


@pytest.mark.asyncio
async def test_approved_shell_write_command_can_run_after_approval(tmp_path):
    emitter = MemoryEmitter()
    llm = ShellWriteLLM()
    service = TaskService(
        emitter=emitter,
        execution_engine=ExecutionEngine(
            emitter=emitter,
            workspace=tmp_path,
            orchestrator=Orchestrator(llm),
        ),
    )
    service._execution_engine._auditor.llm = llm
    task = await service.create_task(
        goal="write approved output directory",
        allowed_tools=["mkdir"],
        acceptance_criteria=["directory exists"],
    )

    waiting = await service.run_task_once(task.id)
    await service.approve_task(task.id, approved_by="operator")
    completed = await service.run_task_once(task.id)

    assert waiting.status == "waiting_approval"
    assert completed.status == "completed"
    assert (tmp_path / "triada-output").is_dir()


@pytest.mark.asyncio
async def test_execution_engine_emits_model_summaries_for_all_agents(tmp_path):
    emitter = MemoryEmitter()
    llm = AgentSummaryLLM()
    engine = ExecutionEngine(
        emitter=emitter,
        workspace=tmp_path,
        orchestrator=Orchestrator(llm),
    )
    engine._auditor.llm = llm
    task = make_task(goal="Echo safely", allowed_tools=["shell"])

    status = await engine.run_once(task)

    assert status == "completed"
    model_deltas = [
        event
        for event in emitter.events
        if event["event_type"] == "thinking_summary_delta"
        and event["payload"]["source"] == "model"
    ]
    assert [event["agent_id"] for event in model_deltas] == [
        "orchestrator",
        "worker-1",
        "auditor-1",
    ]
    assert [event["payload"]["summary"] for event in model_deltas] == [
        "Orchestrator model planned one safe step.",
        "Worker model prepared tool execution.",
        "Auditor model reviewed worker evidence.",
    ]
    reasoning_events = [
        event
        for event in emitter.events
        if event["event_type"] == "model_reasoning_content_captured"
    ]
    assert [event["agent_id"] for event in reasoning_events] == [
        "orchestrator",
        "worker-1",
        "auditor-1",
    ]
    assert [event["payload"]["raw_reasoning_content"] for event in reasoning_events] == [
        "raw plan reasoning",
        "raw worker_result reasoning",
        "raw audit_verdict reasoning",
    ]
    assert "raw " not in str([event["payload"] for event in model_deltas])
