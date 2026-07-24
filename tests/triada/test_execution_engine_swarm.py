from __future__ import annotations

import pytest

from app.services.execution_engine import ExecutionEngine
from tests.triada.test_execution_engine_runtime import MemoryEmitter, make_task


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
