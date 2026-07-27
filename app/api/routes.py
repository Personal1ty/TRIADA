from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.audit.projection import (
    event_to_sse,
    events_to_public_response,
    swarm_graph_from_events,
    thinking_deltas_from_events,
)
from app.contracts.loader import load_default_swarm_contract
from app.llm.runtime_config import LLMProviderConfig
from app.schemas.llm import LLMConfigRequest, LLMConfigResponse, LLMTestResponse
from app.schemas.tasks import ApprovalRequest, CreateTaskRequest, TaskActionResponse, TaskEventsResponse, TaskResponse

router = APIRouter(prefix="/v1")


@router.get("/swarm/contract")
async def get_swarm_contract() -> dict:
    return load_default_swarm_contract().model_dump(mode="json")


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
        await provider.complete_json("TRIADA provider connectivity test", schema_name="plan")
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
    task = await request.app.state.task_service.create_task(
        goal=payload.goal,
        risk=payload.risk,
        constraints=payload.constraints,
        allowed_tools=payload.allowed_tools,
        acceptance_criteria=payload.acceptance_criteria,
        timeout_seconds=payload.timeout_seconds,
        retry_limit=payload.retry_limit,
        metadata=payload.metadata,
    )
    return _task_response(task)


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: UUID, request: Request) -> TaskResponse:
    task = await _get_task_or_404(task_id, request)
    return _task_response(task)


@router.get("/tasks/{task_id}/events", response_model=TaskEventsResponse)
async def list_task_events(task_id: UUID, request: Request) -> TaskEventsResponse:
    task = await _get_task_or_404(task_id, request)
    events = await request.app.state.event_repository.list_events(task.trace_id)
    return TaskEventsResponse(
        task_id=str(task.id),
        trace_id=str(task.trace_id),
        events=events_to_public_response(events),
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
    return _task_action_response(task, "cancel")


@router.post("/tasks/{task_id}/approve", response_model=TaskActionResponse)
async def approve_task(task_id: UUID, payload: ApprovalRequest, request: Request) -> TaskActionResponse:
    if not payload.approved:
        try:
            task = await request.app.state.task_service.cancel_task(task_id, reason=payload.reason)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found") from exc
        return _task_action_response(task, "reject")
    try:
        task = await request.app.state.task_service.approve_task(task_id, approved_by=payload.approved_by)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found") from exc
    return _task_action_response(task, "approve")


@router.post("/tasks/{task_id}/resume", response_model=TaskActionResponse)
async def resume_task(task_id: UUID, request: Request) -> TaskActionResponse:
    try:
        task = await request.app.state.task_service.resume_task(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found") from exc
    return _task_action_response(task, "resume")


@router.post("/tasks/{task_id}/run_once", response_model=TaskActionResponse)
async def run_task_once(task_id: UUID, request: Request) -> TaskActionResponse:
    try:
        task = await request.app.state.task_service.run_task_once(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found") from exc
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


def _task_action_response(task, action: str) -> TaskActionResponse:
    return TaskActionResponse(task_id=str(task.id), trace_id=str(task.trace_id), status=task.status, action=action)


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
