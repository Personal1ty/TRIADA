from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from app.audit.projection import (
    event_to_sse,
    events_to_public_response,
    checkpoints_from_events,
    memory_notes_from_events,
    memory_graph_from_events,
    parameter_influence_from_events,
    playbook_runs_from_events,
    playbook_benchmarks_from_events,
    playbook_templates_from_events,
    playbook_replays_from_events,
    failure_catalog_from_events,
    resource_usage_from_events,
    resource_economics_from_events,
    research_evidence_from_events,
    research_plan_from_events,
    resource_budget_from_events,
    run_inspector_from_events,
    quality_from_events,
    swarm_graph_from_events,
    thinking_deltas_from_events,
)
from app.contracts.swarm import SwarmContract
from app.contracts.capabilities import capability_matrix, capability_registry
from app.llm.runtime_config import LLMProviderConfig
from app.schemas.llm import LLMConfigRequest, LLMConfigResponse, LLMTestResponse
from app.schemas.tasks import (
    ApprovalRequest,
    CreateTaskRequest,
    DemoRunRequest,
    MemoryNoteRequest,
    MemoryRelationRequest,
    ParameterInfluenceRequest,
    PlaybookRunRequest,
    PlaybookTemplateRequest,
    PlaybookReplayRequest,
    FailurePatternRequest,
    ResourceUsageRecordRequest,
    RawReasoningRevealRequest,
    RawReasoningRevealResponse,
    ReplayRequest,
    ResearchEvidenceRequest,
    ResearchPlanRequest,
    TaskActionResponse,
    TaskEventsResponse,
    TaskListResponse,
    TaskResponse,
)
from app.services.task_service import InvalidTaskTransition
from app.research.plan import build_research_plan
from app.research.heuristics import build_research_adapter, derive_decision_heuristics

router = APIRouter(prefix="/v1")


@router.get("/swarm/capabilities")
async def get_swarm_capabilities() -> dict:
    return {"roles": capability_matrix()}


@router.get("/capabilities/registry")
async def get_capability_registry() -> dict:
    return {"capabilities": capability_registry()}


@router.get("/swarm/contract")
async def get_swarm_contract(request: Request, version: str | None = Query(default=None, max_length=64)) -> dict:
    contract = await request.app.state.swarm_contract_repository.get_contract(version)
    if contract is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="swarm contract version not found")
    return contract.model_dump(mode="json")


@router.get("/swarm/contracts")
async def list_swarm_contract_versions(request: Request) -> dict:
    active_version, versions, version_details = await request.app.state.swarm_contract_repository.list_versions()
    return {
        "active_version": active_version,
        "versions": versions,
        "version_details": version_details,
    }


@router.get("/swarm/contract/diff")
async def diff_swarm_contract_versions(
    request: Request,
    from_version: str = Query(min_length=1, max_length=64),
    to_version: str = Query(min_length=1, max_length=64),
) -> dict:
    from_contract = await request.app.state.swarm_contract_repository.get_contract(from_version)
    to_contract = await request.app.state.swarm_contract_repository.get_contract(to_version)
    if from_contract is None or to_contract is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="swarm contract version not found")
    changes: list[dict] = []
    before_payload = from_contract.model_dump(mode="json")
    after_payload = to_contract.model_dump(mode="json")
    before_payload.pop("contract_version", None)
    after_payload.pop("contract_version", None)
    _collect_contract_changes(
        before_payload,
        after_payload,
        path="",
        changes=changes,
    )
    return {"from_version": from_version, "to_version": to_version, "changes": changes}


@router.post("/swarm/contract")
async def save_swarm_contract(payload: dict, request: Request) -> dict:
    metadata = payload.get("__metadata") if isinstance(payload.get("__metadata"), dict) else {}
    contract_payload = {key: value for key, value in payload.items() if key != "__metadata"}
    contract = SwarmContract.model_validate(contract_payload)
    await request.app.state.swarm_contract_repository.save_contract(contract, activate=True, metadata=metadata)
    request.app.state.execution_engine.set_swarm_contract(contract)
    return contract.model_dump(mode="json")


@router.get("/demo/templates")
async def list_demo_templates() -> dict:
    return {"templates": _demo_templates()}


@router.post("/demo/run")
async def run_demo_template(payload: DemoRunRequest, request: Request) -> dict:
    templates = {template["id"]: template for template in _demo_templates()}
    template = templates.get(payload.template_id)
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="demo template not found")

    task = await request.app.state.task_service.create_task(
        goal=template["goal"],
        allowed_tools=template["allowed_tools"],
        acceptance_criteria=template["acceptance_criteria"],
        metadata={"demo_template_id": template["id"], "demo_template_name": template["name"]},
    )
    actions = ["created"]
    task = await request.app.state.task_service.run_task_once(task.id)
    actions.append("run_once")
    if task.status == "waiting_approval":
        task = await request.app.state.task_service.approve_task(task.id, approved_by="demo-flow")
        actions.append("approve")
        task = await request.app.state.task_service.run_task_once(task.id)
        actions.append("run_once")

    events = await request.app.state.event_repository.list_events(task.trace_id)
    return {
        "template_id": template["id"],
        "task": _task_response(task).model_dump(mode="json"),
        "actions": actions,
        "graph": swarm_graph_from_events(events),
        "thinking": {
            "task_id": str(task.id),
            "trace_id": str(task.trace_id),
            "deltas": thinking_deltas_from_events(events),
        },
        "events": {
            "task_id": str(task.id),
            "trace_id": str(task.trace_id),
            "limit": len(events),
            "next_cursor": None,
            "has_more": False,
            "raw_reasoning_refs": _raw_reasoning_refs(events),
            "events": _events_without_raw_reasoning(events),
        },
    }


def _demo_templates() -> list[dict]:
    return [
            {
                "id": "git_status",
                "name": "Git status check",
                "goal": "Inspect the TRIADA repository state with git status and summarize the result.",
                "allowed_tools": ["git"],
                "acceptance_criteria": ["git status was inspected", "result is ready for a human"],
            },
            {
                "id": "repo_health_review",
                "name": "Repository health review",
                "goal": (
                    "Inspect TRIADA repository health using only these safe read-only commands: "
                    "git status; rg --files app/services app/agents; sed -n 1,40p README.md. "
                    "Then summarize what git state, ExecutionEngine/Worker source locations, and the README "
                    "introduction say about the current framework state."
                ),
                "allowed_tools": ["git", "rg", "sed"],
                "acceptance_criteria": [
                    "git status was checked",
                    "ExecutionEngine and Worker files were located",
                    "README introduction was inspected",
                    "summary is ready for a human reviewer",
                ],
            },
            {
                "id": "thinking_capture",
                "name": "Thinking capture smoke test",
                "goal": "Use echo to produce a short TRIADA thinking capture demo message.",
                "allowed_tools": ["echo"],
                "acceptance_criteria": [
                    "orchestrator public thinking summary is stored",
                    "worker public thinking summary is stored",
                    "audit events are visible in the UI",
                ],
            },
            {
                "id": "approval_gate",
                "name": "Approval gate demo",
                "goal": "Prepare a write action that must wait for approval before continuing.",
                "allowed_tools": ["shell"],
                "acceptance_criteria": ["task enters waiting_approval before any write action"],
            },
            {
                "id": "write_file_approval",
                "name": "Approved file write",
                "goal": (
                    "Create a local file named triada-demo-output.txt with a short summary that says "
                    "TRIADA executed an approved write step."
                ),
                "allowed_tools": ["write_file"],
                "acceptance_criteria": [
                    "task waits for approval before writing",
                    "triada-demo-output.txt exists after approval and second run",
                ],
            },
        ]


@router.get("/llm/config", response_model=LLMConfigResponse)
async def get_llm_config(request: Request) -> dict:
    return request.app.state.llm_config_service.public_config()


@router.post("/llm/config", response_model=LLMConfigResponse)
async def save_llm_config(payload: LLMConfigRequest, request: Request) -> dict:
    current_config = request.app.state.llm_config_service.current_config()
    if payload.clear_api_key:
        api_key = None
    elif payload.api_key:
        api_key = payload.api_key
    else:
        api_key = current_config.api_key
    saved = request.app.state.llm_config_service.save(
        LLMProviderConfig(
            provider=payload.provider,
            base_url=payload.base_url,
            model=payload.model,
            api_key=api_key,
        )
    )
    return {
        "provider": saved.provider,
        "base_url": saved.base_url,
        "model": saved.model,
        "has_api_key": bool(saved.api_key),
        "source": saved.source,
    }


@router.post("/llm/test", response_model=LLMTestResponse)
async def test_llm_config(request: Request) -> dict:
    config = request.app.state.llm_config_service.current_config()
    provider = request.app.state.execution_engine._build_llm_provider()
    try:
        await provider.complete_json(
            'TRIADA provider connectivity test. Return only JSON: {"answer":{"ok":true}}',
            schema_name="plan",
        )
    except Exception as exc:
        return {
            "ok": False,
            "provider": config.provider,
            "base_url": config.base_url,
            "model": config.model,
            "error": _redact_secret(str(exc), config.api_key),
        }
    return {
        "ok": True,
        "provider": config.provider,
        "base_url": config.base_url,
        "model": config.model,
        "error": None,
    }


@router.post("/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(payload: CreateTaskRequest, request: Request) -> TaskResponse:
    metadata = dict(payload.metadata)
    metadata["resource_budget"] = payload.resource_budget.model_dump(mode="json")
    task = await request.app.state.task_service.create_task(
        goal=payload.goal,
        risk=payload.risk,
        constraints=payload.constraints,
        allowed_tools=payload.allowed_tools,
        acceptance_criteria=payload.acceptance_criteria,
        timeout_seconds=payload.timeout_seconds,
        retry_limit=payload.retry_limit,
        metadata=metadata,
    )
    return _task_response(task)


@router.get("/tasks", response_model=TaskListResponse)
async def list_tasks(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status", min_length=1, max_length=64),
) -> TaskListResponse:
    tasks = await request.app.state.task_service.list_tasks(limit=limit, status=status_filter)
    return TaskListResponse(tasks=[_task_summary_response(task) for task in tasks])


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: UUID, request: Request) -> TaskResponse:
    task = await _get_task_or_404(task_id, request)
    return _task_response(task)


@router.get("/tasks/{task_id}/events", response_model=TaskEventsResponse)
async def list_task_events(
    task_id: UUID,
    request: Request,
    event_type: str | None = Query(default=None, min_length=1, max_length=255),
    agent_id: str | None = Query(default=None, min_length=1, max_length=255),
    trace_id: UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    after_event_id: UUID | None = Query(default=None),
) -> TaskEventsResponse:
    task = await _get_task_or_404(task_id, request)
    if trace_id is not None and trace_id != task.trace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="trace_id not found for task")
    if after_event_id is not None and not await _event_id_belongs_to_trace(request, task.trace_id, after_event_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="after_event_id not found for task")
    events = await request.app.state.event_repository.list_events(task.trace_id)
    if event_type is not None:
        events = [event for event in events if event.event_type == event_type]
    if agent_id is not None:
        events = [event for event in events if event.agent_id == agent_id]
    if after_event_id is not None:
        after_id = str(after_event_id)
        for index, event in enumerate(events):
            if event.id == after_id:
                events = events[index + 1 :]
                break
        else:
            events = []
    page_events = events[:limit]
    has_more = len(events) > limit
    return TaskEventsResponse(
        task_id=str(task.id),
        trace_id=str(task.trace_id),
        limit=limit,
        next_cursor=str(page_events[-1].id) if has_more and page_events else None,
        has_more=has_more,
        raw_reasoning_refs=_raw_reasoning_refs(page_events),
        events=_events_without_raw_reasoning(page_events),
    )


@router.get("/tasks/{task_id}/stream")
async def stream_task_events(
    task_id: UUID,
    request: Request,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    task = await _get_task_or_404(task_id, request)
    after_event_id = _parse_optional_uuid(last_event_id, "Last-Event-ID")
    if after_event_id is not None and not await _event_id_belongs_to_trace(request, task.trace_id, after_event_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Last-Event-ID not found for task")

    async def event_stream() -> AsyncIterator[str]:
        sent_event_ids: set[str] = set()
        subscription = await request.app.state.event_bus.subscribe(task.trace_id)
        events = await request.app.state.event_repository.list_events(task.trace_id, after_event_id)
        for event in events:
            sent_event_ids.add(str(event.id))
            yield _format_sse(event_to_sse(event))
        try:
            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(
                        subscription.__anext__(),
                        timeout=request.app.state.sse_idle_timeout_seconds,
                    )
                except asyncio.TimeoutError:
                    break
                if str(event.id) in sent_event_ids:
                    continue
                sent_event_ids.add(str(event.id))
                yield _format_sse(event_to_sse(event))
        finally:
            await subscription.aclose()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/tasks/{task_id}/raw-reasoning/{event_id}/reveal", response_model=RawReasoningRevealResponse)
async def reveal_raw_reasoning(
    task_id: UUID,
    event_id: UUID,
    payload: RawReasoningRevealRequest,
    request: Request,
) -> RawReasoningRevealResponse:
    if not payload.acknowledge_sensitive:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="sensitive reveal acknowledgement required")
    task = await _get_task_or_404(task_id, request)
    events = await request.app.state.event_repository.list_events(task.trace_id)
    event = next((item for item in events if str(item.id) == str(event_id)), None)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="reasoning event not found for task")
    event_payload = event.payload if isinstance(event.payload, dict) else {}
    raw_reasoning_content = event_payload.get("raw_reasoning_content")
    if not isinstance(raw_reasoning_content, str) or not raw_reasoning_content:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="raw reasoning content not found")
    return RawReasoningRevealResponse(
        task_id=str(task.id),
        trace_id=str(task.trace_id),
        event_id=str(event.id),
        agent_id=event.agent_id,
        raw_reasoning_content=raw_reasoning_content,
    )


@router.get("/tasks/{task_id}/thinking-summary")
async def get_thinking_summary(task_id: UUID, request: Request) -> dict:
    task = await _get_task_or_404(task_id, request)
    events = await request.app.state.event_repository.list_events(task.trace_id)
    return {
        "task_id": str(task.id),
        "trace_id": str(task.trace_id),
        "deltas": thinking_deltas_from_events(events),
    }


@router.get("/tasks/{task_id}/swarm-graph")
async def get_task_swarm_graph(task_id: UUID, request: Request) -> dict:
    task = await _get_task_or_404(task_id, request)
    events = await request.app.state.event_repository.list_events(task.trace_id)
    return swarm_graph_from_events(events)


@router.get("/tasks/{task_id}/inspector")
async def get_task_inspector(task_id: UUID, request: Request) -> dict:
    task = await _get_task_or_404(task_id, request)
    events = await request.app.state.event_repository.list_events(task.trace_id)
    return {
        "task_id": str(task.id),
        "trace_id": str(task.trace_id),
        "status": task.status,
        "inspector": run_inspector_from_events(events),
    }


@router.get("/tasks/{task_id}/quality")
async def get_task_quality(task_id: UUID, request: Request) -> dict:
    task = await _get_task_or_404(task_id, request)
    events = await request.app.state.event_repository.list_events(task.trace_id)
    return {
        "task_id": str(task.id),
        "trace_id": str(task.trace_id),
        "status": task.status,
        "quality": quality_from_events(events),
    }


@router.get("/tasks/{task_id}/budget")
async def get_task_budget(task_id: UUID, request: Request) -> dict:
    task = await _get_task_or_404(task_id, request)
    events = await request.app.state.event_repository.list_events(task.trace_id)
    projection = resource_budget_from_events(events)
    configured = task.metadata.get("resource_budget") if isinstance(task.metadata, Mapping) else None
    if not any(projection["metrics"].values()) and isinstance(configured, Mapping):
        projection["budget"] = dict(configured)
    return {
        "task_id": str(task.id),
        "trace_id": str(task.trace_id),
        "status": task.status,
        **projection,
    }


@router.get("/tasks/{task_id}/economics")
async def get_task_economics(task_id: UUID, request: Request) -> dict:
    task = await _get_task_or_404(task_id, request)
    events = await request.app.state.event_repository.list_events(task.trace_id)
    configured = task.metadata.get("resource_budget") if isinstance(task.metadata, Mapping) else None
    return {"task_id": str(task.id), "trace_id": str(task.trace_id), **resource_economics_from_events(events, configured_budget=configured if isinstance(configured, Mapping) else None)}


@router.post("/tasks/{task_id}/usage", status_code=status.HTTP_201_CREATED)
async def add_resource_usage(task_id: UUID, payload: ResourceUsageRecordRequest, request: Request) -> dict:
    task = await _get_task_or_404(task_id, request)
    usage_id = uuid4()
    event = await request.app.state.event_repository.append_event(
        event_type="resource_usage_recorded",
        trace_id=task.trace_id,
        task_id=task.id,
        agent_id=payload.agent_role,
        payload={"schema_version": "1.0", "usage_id": str(usage_id), **payload.model_dump(mode="json")},
    )
    return {"usage_id": str(usage_id), "event_id": str(event.id), **payload.model_dump(mode="json")}


@router.get("/tasks/{task_id}/usage")
async def get_resource_usage(task_id: UUID, request: Request) -> dict:
    task = await _get_task_or_404(task_id, request)
    events = await request.app.state.event_repository.list_events(task.trace_id)
    return {"task_id": str(task.id), "trace_id": str(task.trace_id), **resource_usage_from_events(events)}


@router.post("/tasks/{task_id}/playbook/runs", status_code=status.HTTP_201_CREATED)
async def add_playbook_run(task_id: UUID, payload: PlaybookRunRequest, request: Request) -> dict:
    task = await _get_task_or_404(task_id, request)
    run_id = uuid4()
    event = await request.app.state.event_repository.append_event(
        event_type="playbook_run_recorded", trace_id=task.trace_id, task_id=task.id,
        agent_id="operator", payload={"schema_version": "1.0", "run_id": str(run_id), **payload.model_dump(mode="json")},
    )
    return {"run_id": str(run_id), "event_id": str(event.id), **payload.model_dump(mode="json")}


@router.get("/tasks/{task_id}/playbook/runs")
async def get_playbook_runs(task_id: UUID, request: Request) -> dict:
    task = await _get_task_or_404(task_id, request)
    events = await request.app.state.event_repository.list_events(task.trace_id)
    return {"task_id": str(task.id), "trace_id": str(task.trace_id), **playbook_runs_from_events(events)}


@router.post("/tasks/{task_id}/playbook/template", status_code=status.HTTP_201_CREATED)
async def create_playbook_template(task_id: UUID, payload: PlaybookTemplateRequest, request: Request) -> dict:
    task = await _get_task_or_404(task_id, request)
    template_id = uuid4()
    event = await request.app.state.event_repository.append_event(
        event_type="playbook_template_created", trace_id=task.trace_id, task_id=task.id,
        agent_id="operator", payload={"schema_version": "1.0", "template_id": str(template_id), **payload.model_dump(mode="json")},
    )
    return {"template_id": str(template_id), "event_id": str(event.id), **payload.model_dump(mode="json")}


@router.get("/playbooks/templates")
async def list_playbook_templates(request: Request) -> dict:
    events = await request.app.state.event_repository.list_events_by_type("playbook_template_created")
    return playbook_templates_from_events(events)


@router.get("/playbooks/benchmarks")
async def list_playbook_benchmarks(request: Request) -> dict:
    events = await request.app.state.event_repository.list_events_by_type("playbook_run_recorded")
    return playbook_benchmarks_from_events(events)


@router.post("/tasks/{task_id}/playbook/replays", status_code=status.HTTP_201_CREATED)
async def request_playbook_replay(task_id: UUID, payload: PlaybookReplayRequest, request: Request) -> dict:
    task = await _get_task_or_404(task_id, request)
    replay_id = uuid4()
    event = await request.app.state.event_repository.append_event(event_type="playbook_replay_requested", trace_id=task.trace_id, task_id=task.id, agent_id="operator", payload={"schema_version": "1.0", "replay_id": str(replay_id), "status": "requested", **payload.model_dump(mode="json")})
    return {"replay_id": str(replay_id), "event_id": str(event.id), "status": "requested", **payload.model_dump(mode="json")}


@router.get("/tasks/{task_id}/playbook/replays")
async def get_playbook_replays(task_id: UUID, request: Request) -> dict:
    task = await _get_task_or_404(task_id, request)
    events = await request.app.state.event_repository.list_events(task.trace_id)
    return playbook_replays_from_events(events)


@router.post("/tasks/{task_id}/failures", status_code=status.HTTP_201_CREATED)
async def add_failure_pattern(task_id: UUID, payload: FailurePatternRequest, request: Request) -> dict:
    task = await _get_task_or_404(task_id, request)
    failure_id = uuid4()
    event = await request.app.state.event_repository.append_event(event_type="failure_pattern_recorded", trace_id=task.trace_id, task_id=task.id, agent_id="operator", payload={"schema_version": "1.0", "failure_id": str(failure_id), **payload.model_dump(mode="json")})
    return {"failure_id": str(failure_id), "event_id": str(event.id), **payload.model_dump(mode="json")}


@router.get("/failures")
async def list_failure_patterns(request: Request) -> dict:
    events = await request.app.state.event_repository.list_events_by_type("failure_pattern_recorded")
    return failure_catalog_from_events(events)


@router.get("/tasks/{task_id}/research/recommendations")
async def get_research_recommendations(task_id: UUID, request: Request) -> dict:
    task = await _get_task_or_404(task_id, request)
    events = await request.app.state.event_repository.list_events(task.trace_id)
    failures = failure_catalog_from_events(events)["patterns"]
    usage = resource_usage_from_events(events)
    plan = research_plan_from_events(events) or {}
    parameters = plan.get("parameter_catalog") or ["risk", "latency", "parallelism"]
    heuristics = derive_decision_heuristics(failures=failures, usage=usage)
    return {
        "task_id": str(task.id),
        "trace_id": str(task.trace_id),
        "heuristics": heuristics,
        "adapter": build_research_adapter(question=plan.get("question") or task.goal, parameters=parameters),
    }


@router.get("/tasks/{task_id}/checkpoints")
async def get_task_checkpoints(task_id: UUID, request: Request) -> dict:
    task = await _get_task_or_404(task_id, request)
    events = await request.app.state.event_repository.list_events(task.trace_id)
    return {
        "task_id": str(task.id),
        "trace_id": str(task.trace_id),
        "checkpoints": checkpoints_from_events(events),
    }


@router.post("/tasks/{task_id}/research", status_code=status.HTTP_201_CREATED)
async def create_research_plan(task_id: UUID, payload: ResearchPlanRequest, request: Request) -> dict:
    task = await _get_task_or_404(task_id, request)
    plan_id = uuid4()
    plan = build_research_plan(**payload.model_dump(mode="json"))
    event = await request.app.state.event_repository.append_event(
        event_type="research_plan_created",
        trace_id=task.trace_id,
        task_id=task.id,
        agent_id="human",
        payload={"schema_version": "1.0", "research_id": str(plan_id), **plan},
    )
    return {**plan, "research_id": str(plan_id), "event_id": str(event.id)}


@router.get("/tasks/{task_id}/research")
async def get_research_plan(task_id: UUID, request: Request) -> dict:
    task = await _get_task_or_404(task_id, request)
    events = await request.app.state.event_repository.list_events(task.trace_id)
    plan = research_plan_from_events(events)
    return {"task_id": str(task.id), "trace_id": str(task.trace_id), "plan": plan}


@router.post("/tasks/{task_id}/research/evidence", status_code=status.HTTP_201_CREATED)
async def add_research_evidence(task_id: UUID, payload: ResearchEvidenceRequest, request: Request) -> dict:
    task = await _get_task_or_404(task_id, request)
    evidence_id = uuid4()
    event = await request.app.state.event_repository.append_event(
        event_type="research_evidence_added",
        trace_id=task.trace_id,
        task_id=task.id,
        agent_id="human",
        payload={
            "schema_version": "1.0",
            "evidence_id": str(evidence_id),
            **payload.model_dump(mode="json"),
        },
    )
    return {"evidence_id": str(evidence_id), "event_id": str(event.id), **payload.model_dump(mode="json")}


@router.get("/tasks/{task_id}/research/evidence")
async def get_research_evidence(task_id: UUID, request: Request) -> dict:
    task = await _get_task_or_404(task_id, request)
    events = await request.app.state.event_repository.list_events(task.trace_id)
    return {"task_id": str(task.id), "trace_id": str(task.trace_id), **research_evidence_from_events(events)}


@router.post("/tasks/{task_id}/research/influence", status_code=status.HTTP_201_CREATED)
async def add_parameter_influence(task_id: UUID, payload: ParameterInfluenceRequest, request: Request) -> dict:
    task = await _get_task_or_404(task_id, request)
    influence_id = uuid4()
    event = await request.app.state.event_repository.append_event(
        event_type="parameter_influence_recorded",
        trace_id=task.trace_id,
        task_id=task.id,
        agent_id="human",
        payload={"schema_version": "1.0", "influence_id": str(influence_id), **payload.model_dump(mode="json")},
    )
    return {"influence_id": str(influence_id), "event_id": str(event.id), **payload.model_dump(mode="json")}


@router.get("/tasks/{task_id}/research/influence")
async def get_parameter_influence(task_id: UUID, request: Request) -> dict:
    task = await _get_task_or_404(task_id, request)
    events = await request.app.state.event_repository.list_events(task.trace_id)
    return {"task_id": str(task.id), "trace_id": str(task.trace_id), **parameter_influence_from_events(events)}


@router.post("/tasks/{task_id}/memory", status_code=status.HTTP_201_CREATED)
async def add_task_memory(task_id: UUID, payload: MemoryNoteRequest, request: Request) -> dict:
    task = await _get_task_or_404(task_id, request)
    memory_id = uuid4()
    event = await request.app.state.event_repository.append_event(
        event_type="memory_note_added",
        trace_id=task.trace_id,
        task_id=task.id,
        agent_id="human",
        payload={
            "schema_version": "1.0",
            "memory_id": str(memory_id),
            **payload.model_dump(mode="json"),
        },
    )
    memory_index = request.app.state.memory_index
    if memory_index is not None:
        try:
            await memory_index.index_event(event)
        except Exception:
            # The append-only audit event is authoritative; indexing can be rebuilt.
            pass
    return {
        "memory_id": str(memory_id),
        "event_id": str(event.id),
        **payload.model_dump(mode="json"),
    }


@router.get("/tasks/{task_id}/memory")
async def get_task_memory(
    task_id: UUID,
    request: Request,
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    task = await _get_task_or_404(task_id, request)
    memory_index = request.app.state.memory_index
    if q and memory_index is not None:
        try:
            notes = [note for note in await memory_index.search(q, limit=limit) if note["task_id"] == str(task.id)]
            return {
                "task_id": str(task.id),
                "trace_id": str(task.trace_id),
                "query": q,
                "backend": "pgvector",
                "notes": notes,
            }
        except Exception:
            pass
    events = await request.app.state.event_repository.list_events(task.trace_id)
    return {
        "task_id": str(task.id),
        "trace_id": str(task.trace_id),
        "query": q or "",
        "backend": "lexical",
        "notes": memory_notes_from_events(events, query=q, limit=limit),
    }


@router.post("/tasks/{task_id}/memory/relations", status_code=status.HTTP_201_CREATED)
async def add_memory_relation(task_id: UUID, payload: MemoryRelationRequest, request: Request) -> dict:
    task = await _get_task_or_404(task_id, request)
    relation_id = uuid4()
    event = await request.app.state.event_repository.append_event(
        event_type="memory_relation_added",
        trace_id=task.trace_id,
        task_id=task.id,
        agent_id="human",
        payload={
            "schema_version": "1.0",
            "relation_id": str(relation_id),
            **payload.model_dump(mode="json"),
        },
    )
    return {"relation_id": str(relation_id), "event_id": str(event.id), **payload.model_dump(mode="json")}


@router.get("/tasks/{task_id}/memory/graph")
async def get_task_memory_graph(task_id: UUID, request: Request) -> dict:
    task = await _get_task_or_404(task_id, request)
    events = await request.app.state.event_repository.list_events(task.trace_id)
    return {
        "task_id": str(task.id),
        "trace_id": str(task.trace_id),
        **memory_graph_from_events(events),
    }


@router.get("/memory/search")
async def search_memory(
    request: Request,
    q: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    memory_index = request.app.state.memory_index
    if memory_index is not None:
        try:
            return {"query": q, "backend": "pgvector", "notes": await memory_index.search(q, limit=limit)}
        except Exception:
            pass
    events = await request.app.state.event_repository.list_events_by_type("memory_note_added")
    return {
        "query": q,
        "backend": "lexical",
        "notes": memory_notes_from_events(events, query=q, limit=limit),
    }


@router.get("/memory/graph")
async def get_global_memory_graph(request: Request) -> dict:
    events = await request.app.state.event_repository.list_events_by_type(
        "memory_note_added"
    )
    relation_events = await request.app.state.event_repository.list_events_by_type(
        "memory_relation_added"
    )
    return memory_graph_from_events([*events, *relation_events])


@router.post("/tasks/{task_id}/replay", response_model=TaskActionResponse, status_code=status.HTTP_201_CREATED)
async def replay_task(task_id: UUID, payload: ReplayRequest, request: Request) -> TaskActionResponse:
    source = await _get_task_or_404(task_id, request)
    try:
        event_id = UUID(payload.from_event_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid from_event_id") from exc
    if not await _event_id_belongs_to_trace(request, source.trace_id, event_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="replay event not found for task")
    replay = await request.app.state.task_service.create_replay_task(
        source.id,
        from_event_id=event_id,
        requested_by=payload.requested_by,
        reason=payload.reason,
    )
    return _task_action_response(replay, "replay_requested")


@router.get("/tasks/{task_id}/audit")
async def get_task_audit(task_id: UUID, request: Request) -> dict:
    task = await _get_task_or_404(task_id, request)
    events = await request.app.state.event_repository.list_events(task.trace_id)
    return {
        "task_id": str(task.id),
        "trace_id": str(task.trace_id),
        "hash_chain_valid": await request.app.state.event_repository.verify_trace(task.trace_id),
        "events": events_to_public_response(events),
    }


@router.get("/tasks/{task_id}/artifacts")
async def get_task_artifacts(task_id: UUID, request: Request) -> dict:
    task = await _get_task_or_404(task_id, request)
    events = await request.app.state.event_repository.list_events(task.trace_id)
    artifacts = []
    for event in events:
        if event.event_type == "artifact_created":
            artifacts.append(event.payload)
    return {"task_id": str(task.id), "trace_id": str(task.trace_id), "artifacts": artifacts}


@router.post("/tasks/{task_id}/cancel", response_model=TaskActionResponse)
async def cancel_task(task_id: UUID, request: Request) -> TaskActionResponse:
    try:
        task = await request.app.state.task_service.cancel_task(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found") from exc
    except InvalidTaskTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _task_action_response(task, "cancel")


@router.post("/tasks/{task_id}/approve", response_model=TaskActionResponse)
async def approve_task(task_id: UUID, payload: ApprovalRequest, request: Request) -> TaskActionResponse:
    if not payload.approved:
        try:
            task = await request.app.state.task_service.cancel_task(task_id, reason=payload.reason)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found") from exc
        except InvalidTaskTransition as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        return _task_action_response(task, "reject")
    try:
        task = await request.app.state.task_service.approve_task(task_id, approved_by=payload.approved_by)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found") from exc
    except InvalidTaskTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _task_action_response(task, "approve")


@router.post("/tasks/{task_id}/resume", response_model=TaskActionResponse)
async def resume_task(task_id: UUID, request: Request) -> TaskActionResponse:
    try:
        task = await request.app.state.task_service.resume_task(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found") from exc
    except InvalidTaskTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _task_action_response(task, "resume")


@router.post("/tasks/{task_id}/run_once", response_model=TaskActionResponse)
async def run_task_once(task_id: UUID, request: Request) -> TaskActionResponse:
    try:
        task = await request.app.state.task_service.run_task_once(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found") from exc
    except InvalidTaskTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _task_action_response(task, "run_once")


async def _get_task_or_404(task_id: UUID, request: Request):
    task = await request.app.state.task_service.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    return task


async def _event_id_belongs_to_trace(request: Request, trace_id: UUID, event_id: UUID) -> bool:
    events = await request.app.state.event_repository.list_events(trace_id)
    return any(str(event.id) == str(event_id) for event in events)


def _task_response(task) -> TaskResponse:
    return TaskResponse(task_id=str(task.id), trace_id=str(task.trace_id), status=task.status)


def _collect_contract_changes(before, after, *, path: str, changes: list[dict]) -> None:
    if isinstance(before, Mapping) and isinstance(after, Mapping):
        for key in sorted(set(before) | set(after)):
            child_path = f"{path}.{key}" if path else str(key)
            if key not in before:
                changes.append({"path": child_path, "before": None, "after": after[key]})
            elif key not in after:
                changes.append({"path": child_path, "before": before[key], "after": None})
            else:
                _collect_contract_changes(before[key], after[key], path=child_path, changes=changes)
        return
    if before != after:
        changes.append({"path": path, "before": before, "after": after})


def _task_summary_response(task) -> dict:
    return {
        "task_id": str(task.id),
        "trace_id": str(task.trace_id),
        "status": task.status,
        "goal": task.goal,
        "allowed_tools": task.allowed_tools,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
    }


def _task_action_response(task, action: str) -> TaskActionResponse:
    return TaskActionResponse(task_id=str(task.id), trace_id=str(task.trace_id), status=task.status, action=action)


def _events_without_raw_reasoning(events: list) -> list[dict]:
    return events_to_public_response(events)


def _raw_reasoning_refs(events: list) -> list[dict]:
    refs: list[dict] = []
    for event in events:
        if event.event_type != "model_reasoning_content_captured":
            continue
        refs.append(
            {
                "event_id": str(event.id),
                "agent_id": event.agent_id,
                "sequence": event.sequence,
                "created_at": event.created_at.isoformat(),
            }
        )
    return refs


def _parse_optional_uuid(value: str | None, header_name: str) -> UUID | None:
    if value is None or value == "":
        return None
    try:
        return UUID(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"invalid {header_name}",
        ) from exc


def _format_sse(message: dict[str, str]) -> str:
    lines = [f"id: {message['id']}", f"event: {message['event']}"]
    data = json.loads(message["data"])
    lines.append(f"data: {json.dumps(data, sort_keys=True)}")
    return "\n".join(lines) + "\n\n"


def _redact_secret(value: str, secret: str | None) -> str:
    if secret:
        return value.replace(secret, "[redacted]")
    return value
