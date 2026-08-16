from __future__ import annotations

import pytest

from app.agents.orchestrator import Orchestrator
from app.events.models import AuditVerdict
from app.schemas.enums import AuditVerdictValue
from app.services.execution_engine import ExecutionEngine
from tests.triada.test_execution_engine_runtime import MemoryEmitter, MultiStepLLM, make_task


class CorrectionsRequiredAuditor:
    llm = None

    async def audit_tool_results_with_model(
        self,
        tool_results,
        worker_summary,
        model_summaries=None,
    ):
        return (
            AuditVerdict(
                verdict=AuditVerdictValue.CORRECTIONS_REQUIRED,
                summary="Corrections are required.",
            ),
            None,
            {},
            None,
        )


class CorrectionsThenPassAuditor:
    llm = None

    def __init__(self) -> None:
        self.calls = 0

    async def audit_tool_results_with_model(
        self,
        tool_results,
        worker_summary,
        model_summaries=None,
    ):
        self.calls += 1
        if self.calls == 1:
            return (
                AuditVerdict(
                    verdict=AuditVerdictValue.CORRECTIONS_REQUIRED,
                    summary="Retry with corrected evidence.",
                    required_corrections=["rerun worker step"],
                ),
                None,
                {},
                None,
            )
        return (
            AuditVerdict(
                verdict=AuditVerdictValue.PASS,
                summary="Correction passed.",
            ),
            None,
            {},
            None,
        )


class SuccessfulThenBlockedLLM:
    async def complete_json(self, prompt: str, *, schema_name: str):
        if schema_name == "plan":
            return {
                "answer": {
                    "steps": [
                        {
                            "id": "step-1",
                            "title": "Echo first",
                            "description": "first step",
                            "allowed_tools": ["shell"],
                        },
                        {
                            "id": "step-2",
                            "title": "Unsupported second",
                            "description": "second step",
                            "allowed_tools": ["unknown"],
                        },
                    ]
                }
            }
        return {}


@pytest.mark.asyncio
async def test_execution_engine_emits_swarm_route_events_from_contract(tmp_path):
    emitter = MemoryEmitter()
    engine = ExecutionEngine(emitter=emitter, workspace=tmp_path)
    task = make_task(goal="Echo repository status", allowed_tools=["shell"])

    status = await engine.run_once(task)

    assert status == "completed"
    route_events = [
        event for event in emitter.events if event["event_type"] == "swarm_route_selected"
    ]
    assert route_events

    assign_route = next(
        event for event in route_events if event["payload"]["reason"] == "assign_step"
    )
    assert assign_route["agent_id"] == "orchestrator"
    assert assign_route["payload"]["source"] == "orchestrator"
    assert assign_route["payload"]["target"] == "worker"
    assert assign_route["payload"]["input_contract"] == "worker_assignment@1.0"
    assert assign_route["payload"]["output_contract"] == "worker_result@1.0"

    submit_route = next(
        event
        for event in route_events
        if event["payload"]["reason"] == "submit_evidence"
    )
    assert submit_route["agent_id"] == "worker-1"
    assert submit_route["payload"]["source"] == "worker"
    assert submit_route["payload"]["target"] == "assigned_auditor"
    assert submit_route["payload"]["input_contract"] == "worker_result@1.0"
    assert submit_route["payload"]["output_contract"] == "audit_verdict@1.0"


@pytest.mark.asyncio
async def test_execution_engine_does_not_submit_evidence_when_worker_blocks(tmp_path):
    emitter = MemoryEmitter()
    engine = ExecutionEngine(emitter=emitter, workspace=tmp_path)
    task = make_task(goal="Echo repository status", allowed_tools=["unknown"])

    status = await engine.run_once(task)

    assert status == "blocked"
    route_reasons = [
        event["payload"]["reason"]
        for event in emitter.events
        if event["event_type"] == "swarm_route_selected"
    ]
    assert "assign_step" in route_reasons
    assert "submit_evidence" not in route_reasons


@pytest.mark.asyncio
async def test_execution_engine_does_not_submit_partial_evidence_after_later_block(tmp_path):
    emitter = MemoryEmitter()
    engine = ExecutionEngine(
        emitter=emitter,
        workspace=tmp_path,
        orchestrator=Orchestrator(SuccessfulThenBlockedLLM()),
    )
    task = make_task(
        goal="Run a supported step then an unsupported step",
        allowed_tools=["shell", "unknown"],
    )

    status = await engine.run_once(task)

    assert status == "blocked"
    route_reasons = [
        event["payload"]["reason"]
        for event in emitter.events
        if event["event_type"] == "swarm_route_selected"
    ]
    assert route_reasons == ["assign_step", "assign_step"]
    event_types = [event["event_type"] for event in emitter.events]
    assert "worker_step_completed" in event_types
    assert "worker_step_blocked" in event_types
    assert "tool_execution_completed" in event_types
    assert "audit_verdict" not in event_types
    assert "chief_audit_verdict" not in event_types
    assert "human_review_packet_created" not in event_types


@pytest.mark.asyncio
async def test_execution_engine_audits_failed_worker_tool_evidence(tmp_path):
    emitter = MemoryEmitter()
    engine = ExecutionEngine(emitter=emitter, workspace=tmp_path)
    task = make_task(goal="Inspect repository status", allowed_tools=["git"])

    status = await engine.run_once(task)

    assert status == "failed"
    route_reasons = [
        event["payload"]["reason"]
        for event in emitter.events
        if event["event_type"] == "swarm_route_selected"
    ]
    assert route_reasons == [
        "assign_step",
        "submit_evidence",
        "escalate_verdict",
        "return_final_gate",
        "deliver_human_packet",
    ]
    event_types = [event["event_type"] for event in emitter.events]
    assert "worker_step_failed" in event_types
    assert "tool_execution_completed" in event_types
    assert "audit_verdict" in event_types
    assert "chief_audit_verdict" in event_types
    assert "human_review_packet_created" in event_types

    human_packet = next(
        event
        for event in emitter.events
        if event["event_type"] == "human_review_packet_created"
    )
    assert human_packet["payload"]["status"] == "failed"
    assert human_packet["payload"]["tool_result_count"] >= 1


@pytest.mark.asyncio
async def test_execution_engine_emits_chief_auditor_gate_before_human_packet(tmp_path):
    emitter = MemoryEmitter()
    engine = ExecutionEngine(emitter=emitter, workspace=tmp_path)
    task = make_task(goal="Echo repository status", allowed_tools=["shell"])

    status = await engine.run_once(task)

    assert status == "completed"
    event_types = [event["event_type"] for event in emitter.events]
    audit_index = event_types.index("audit_verdict")
    chief_index = event_types.index("chief_audit_verdict")
    packet_index = event_types.index("human_review_packet_created")
    assert audit_index < chief_index < packet_index
    deliver_index = next(
        index
        for index, event in enumerate(emitter.events)
        if event["event_type"] == "swarm_route_selected"
        and event["payload"]["reason"] == "deliver_human_packet"
    )
    assert packet_index < deliver_index

    route_events = [
        event for event in emitter.events if event["event_type"] == "swarm_route_selected"
    ]
    routes_by_reason = {
        event["payload"]["reason"]: event["payload"] for event in route_events
    }
    route_events_by_reason = {
        event["payload"]["reason"]: event for event in route_events
    }
    assert route_events_by_reason["escalate_verdict"]["agent_id"] == "auditor-1"
    assert routes_by_reason["escalate_verdict"]["source"] == "assigned_auditor"
    assert routes_by_reason["escalate_verdict"]["target"] == "chief_auditor"
    assert routes_by_reason["escalate_verdict"]["input_contract"] == "audit_verdict@1.0"
    assert routes_by_reason["escalate_verdict"]["output_contract"] == "chief_audit_verdict@1.0"
    assert routes_by_reason["return_final_gate"]["source"] == "chief_auditor"
    assert routes_by_reason["return_final_gate"]["target"] == "orchestrator"
    assert routes_by_reason["return_final_gate"]["input_contract"] == "chief_audit_verdict@1.0"
    assert routes_by_reason["return_final_gate"]["output_contract"] == "human_review_packet@1.0"
    assert routes_by_reason["deliver_human_packet"]["source"] == "orchestrator"
    assert routes_by_reason["deliver_human_packet"]["target"] == "human"
    assert routes_by_reason["deliver_human_packet"]["input_contract"] == "human_review_packet@1.0"
    assert routes_by_reason["deliver_human_packet"]["output_contract"] == "human_decision@1.0"

    chief_verdict = next(
        event for event in emitter.events if event["event_type"] == "chief_audit_verdict"
    )
    assert chief_verdict["agent_id"] == "chief-auditor"
    assert chief_verdict["payload"]["schema_version"] == "1.0"
    assert chief_verdict["payload"]["chief_auditor_id"] == "chief-auditor"
    assert chief_verdict["payload"]["verdict"] == "pass"
    assert chief_verdict["payload"]["source_verdict_refs"] == ["audit_verdict"]
    assert "summary" in chief_verdict["payload"]
    assert chief_verdict["payload"]["agent_id"] == "chief-auditor"

    human_packet = next(
        event
        for event in emitter.events
        if event["event_type"] == "human_review_packet_created"
    )
    assert human_packet["agent_id"] == "orchestrator"
    assert human_packet["payload"]["agent_id"] == "orchestrator"
    assert human_packet["payload"]["schema_version"] == "1.0"
    assert human_packet["payload"]["contract"] == {
        "name": "human_review_packet",
        "version": "1.0",
    }
    assert human_packet["payload"]["status"] == "completed"
    assert human_packet["payload"]["chief_auditor_verdict"] == chief_verdict["payload"]["verdict"]
    assert "summary" in human_packet["payload"]
    assert human_packet["payload"]["worker_result_count"] == 1
    assert human_packet["payload"]["tool_result_count"] >= 1
    assert human_packet["payload"]["raw_reasoning_refs"] == []


@pytest.mark.asyncio
async def test_execution_engine_routes_corrections_required_verdict_to_human_packet(tmp_path):
    emitter = MemoryEmitter()
    engine = ExecutionEngine(
        emitter=emitter,
        workspace=tmp_path,
        auditor=CorrectionsRequiredAuditor(),
    )
    task = make_task(goal="Echo repository status", allowed_tools=["shell"])

    status = await engine.run_once(task)

    assert status == "corrections_required"
    chief_verdict = next(
        event for event in emitter.events if event["event_type"] == "chief_audit_verdict"
    )
    assert chief_verdict["payload"]["verdict"] == "corrections_required"

    human_packet = next(
        event
        for event in emitter.events
        if event["event_type"] == "human_review_packet_created"
    )
    assert human_packet["payload"]["status"] == "corrections_required"
    assert human_packet["payload"]["chief_auditor_verdict"] == "corrections_required"


@pytest.mark.asyncio
async def test_execution_engine_retries_after_auditor_requests_correction(tmp_path):
    emitter = MemoryEmitter()
    auditor = CorrectionsThenPassAuditor()
    engine = ExecutionEngine(
        emitter=emitter,
        workspace=tmp_path,
        auditor=auditor,
    )
    task = make_task(goal="Echo repository status", allowed_tools=["shell"])
    task.retry_limit = 1

    status = await engine.run_once(task)

    assert status == "completed"
    assert auditor.calls == 2
    event_types = [event["event_type"] for event in emitter.events]
    assert "correction_requested" in event_types
    worker_completed = [
        event for event in emitter.events if event["event_type"] == "worker_step_completed"
    ]
    assert len(worker_completed) == 2
    route_reasons = [
        event["payload"]["reason"]
        for event in emitter.events
        if event["event_type"] == "swarm_route_selected"
    ]
    assert "request_correction" in route_reasons


@pytest.mark.asyncio
async def test_execution_engine_distributes_steps_across_worker_auditor_pairs(tmp_path):
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
    tool_events = [
        event for event in emitter.events if event["event_type"] == "tool_execution_completed"
    ]
    assert [event["agent_id"] for event in tool_events] == ["worker-1", "worker-2"]
    audit_events = [event for event in emitter.events if event["event_type"] == "audit_verdict"]
    assert [event["agent_id"] for event in audit_events] == ["auditor-1", "auditor-2"]
