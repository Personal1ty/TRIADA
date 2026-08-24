import pytest

from app.agents.orchestrator import Orchestrator
from app.contracts.research import ResearchMode
from app.services.completion_gate import CompletionGate
from app.services.execution_engine import ExecutionEngine
from app.services.task_service import TaskService
from app.events.models import AuditVerdict, ArtifactRecord, ToolExecutionRecord
from app.schemas.enums import AuditVerdictValue


class ResearchPlanProvider:
    async def complete_json(self, prompt: str, *, schema_name: str):
        return {"answer": {"steps": [{"id": "step-1", "title": "Inspect", "description": "Inspect", "allowed_tools": ["echo"], "command": ["echo", "evidence"]}]}}


class StructuredOutputSchemaProvider:
    async def complete_json(self, prompt: str, *, schema_name: str):
        return {
            "answer": {
                "steps": [],
                "research_contract": {
                    "output_schema": {"type": "object", "properties": {"result": {"type": "string"}}}
                },
            }
        }


class NumericDepthProvider:
    async def complete_json(self, prompt: str, *, schema_name: str):
        return {
            "answer": {
                "steps": [],
                "research_contract": {"depth": 2},
            }
        }


class ResearchSynthesisProvider:
    async def complete_json(self, prompt: str, *, schema_name: str):
        if schema_name == "plan":
            return {
                "answer": {
                    "steps": [{"id": "step-1", "title": "Inspect", "description": "Inspect", "allowed_tools": ["echo"], "command": ["echo", "evidence"]}],
                    "research_contract": {"min_tool_executions": 1, "required_artifacts": ["research_report"]},
                }
            }
        if schema_name == "research_report":
            return {"answer": {"artifacts": [{"name": "research_report", "content": "Audited report"}]}}
        return {"answer": {}}


class DependencyProvider:
    async def complete_json(self, prompt: str, *, schema_name: str):
        return {
            "answer": {
                "steps": [
                    {
                        "id": "write",
                        "title": "Write",
                        "description": "Write",
                        "allowed_tools": ["write_file"],
                        "command": ["write_file", "triada-dev-tests/x.py", "x = 1\n"],
                        "depends_on": [],
                    },
                    {
                        "id": "test",
                        "title": "Test",
                        "description": "Test",
                        "allowed_tools": ["pytest"],
                        "command": ["pytest", "triada-dev-tests/test_x.py"],
                        "depends_on": ["write"],
                    },
                ]
            }
        }


def _tool_record():
    return ToolExecutionRecord(tool="shell", command=["git", "status"], exit_code=0)


@pytest.mark.asyncio
async def test_orchestrator_builds_research_contract_for_analysis_goal():
    plan = await Orchestrator(ResearchPlanProvider()).plan_task(
        goal="Проведи архитектурный анализ TRIADA и сформулируй улучшения",
        allowed_tools=["echo"],
        acceptance_criteria=["return useful result"],
    )

    assert plan.research_contract.mode == ResearchMode.RESEARCH
    assert plan.research_contract.required_artifacts == ["research_report"]
    assert plan.research_contract.min_tool_executions == 3


@pytest.mark.asyncio
async def test_orchestrator_falls_back_when_output_schema_is_structured_object():
    plan = await Orchestrator(StructuredOutputSchemaProvider()).plan_task(
        goal="Проведи архитектурный анализ TRIADA",
        allowed_tools=["echo"],
        acceptance_criteria=[],
    )

    assert plan.research_contract.output_schema == "research_report"


@pytest.mark.asyncio
async def test_orchestrator_normalizes_numeric_research_depth():
    plan = await Orchestrator(NumericDepthProvider()).plan_task(
        goal="Проведи архитектурный анализ TRIADA",
        allowed_tools=["echo"],
        acceptance_criteria=[],
    )

    assert plan.research_contract.depth == "2"


@pytest.mark.asyncio
async def test_orchestrator_preserves_step_dependencies():
    plan = await Orchestrator(DependencyProvider()).plan_task(
        goal="Implement and test a feature",
        allowed_tools=["write_file", "pytest"],
        acceptance_criteria=[],
    )

    assert plan.steps[1].depends_on == ["write"]


def test_completion_gate_rejects_successful_tool_without_research_artifact():
    verdict = AuditVerdict(verdict=AuditVerdictValue.PASS, summary="Evidence passed")
    result = CompletionGate().evaluate(
        contract={
            "mode": "research",
            "required_artifacts": ["research_report"],
            "min_tool_executions": 3,
        },
        worker_results=[],
        tool_records=[_tool_record()],
        verdicts=[("auditor-1", verdict)],
    )

    assert result.passed is False
    assert "research_report" in result.missing_artifacts
    assert result.reason == "research_contract_not_satisfied"
    assert result.next_action == "replan_research"


def test_completion_gate_accepts_research_artifact_and_minimum_evidence():
    verdict = AuditVerdict(verdict=AuditVerdictValue.PASS, summary="Evidence passed")
    result = CompletionGate().evaluate(
        contract={
            "mode": "research",
            "required_artifacts": ["research_report"],
            "min_tool_executions": 1,
        },
        worker_results=[
            {"artifacts": [ArtifactRecord(name="research_report", artifact_type="markdown")]}
        ],
        tool_records=[_tool_record()],
        verdicts=[("auditor-1", verdict)],
    )

    assert result.passed is True


@pytest.mark.asyncio
async def test_research_run_cannot_complete_after_only_git_status(tmp_path):
    events = []

    class Emitter:
        async def emit(self, **kwargs):
            events.append(kwargs)

    emitter = Emitter()
    engine = ExecutionEngine(
        emitter=emitter,
        workspace=tmp_path,
        orchestrator=Orchestrator(ResearchPlanProvider()),
    )
    service = TaskService(emitter=emitter, execution_engine=engine)
    task = await service.create_task(
        goal="Проведи архитектурный анализ TRIADA и сформулируй улучшения",
        allowed_tools=["echo"],
        acceptance_criteria=["return useful result"],
    )

    failed = await service.run_task_once(task.id)

    assert failed.status == "failed"
    assert any(event["event_type"] == "completion_gate_failed" for event in events)


@pytest.mark.asyncio
async def test_research_run_synthesizes_required_report_after_audited_evidence(tmp_path):
    events = []

    class Emitter:
        async def emit(self, **kwargs):
            events.append(kwargs)

    engine = ExecutionEngine(
        emitter=Emitter(),
        workspace=tmp_path,
        orchestrator=Orchestrator(ResearchSynthesisProvider()),
    )
    service = TaskService(emitter=engine._emitter, execution_engine=engine)
    task = await service.create_task(
        goal="Проведи архитектурный анализ TRIADA",
        allowed_tools=["echo"],
    )

    completed = await service.run_task_once(task.id)

    assert completed.status == "completed"
    assert not any(event["event_type"] == "completion_gate_failed" for event in events)
    report_event = next(event for event in events if event["event_type"] == "research_report_created")
    assert report_event["payload"]["artifacts"] == [
        {
            "name": "research_report",
            "artifact_type": "markdown",
            "content_type": "text/markdown",
            "metadata": {"content": "Audited report"},
        }
    ]
