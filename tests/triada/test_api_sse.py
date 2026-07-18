import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@asynccontextmanager
async def _client() -> AsyncIterator[AsyncClient]:
    app = create_app(testing=True)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client


@pytest.mark.asyncio
async def test_create_task_and_list_events():
    async with _client() as client:
        created = await client.post(
            "/v1/tasks",
            json={
                "goal": "Inspect repository",
                "allowed_tools": ["git"],
                "acceptance_criteria": ["Return git status"],
            },
        )
        assert created.status_code == 201
        task_id = created.json()["task_id"]

        events = await client.get(f"/v1/tasks/{task_id}/events")
        assert events.status_code == 200
        assert events.json()["events"]


@pytest.mark.asyncio
async def test_sse_last_event_id_restores_stream():
    async with _client() as client:
        created = await client.post("/v1/tasks", json={"goal": "Demo", "allowed_tools": ["shell"]})
        task_id = created.json()["task_id"]
        await client.post(f"/v1/tasks/{task_id}/run_once")
        events = (await client.get(f"/v1/tasks/{task_id}/events")).json()["events"]
        first_id = events[0]["id"]
        stream = await client.get(
            f"/v1/tasks/{task_id}/stream",
            headers={"Last-Event-ID": first_id},
        )
        assert stream.status_code == 200
        assert "text/event-stream" in stream.headers["content-type"]
        assert f"id: {first_id}" not in stream.text
        assert f"id: {events[1]['id']}" in stream.text
        assert "event: task_completed" in stream.text


@pytest.mark.asyncio
async def test_sse_last_event_id_must_belong_to_task_trace():
    async with _client() as client:
        first = await client.post("/v1/tasks", json={"goal": "First"})
        second = await client.post("/v1/tasks", json={"goal": "Second"})
        first_task_id = first.json()["task_id"]
        second_task_id = second.json()["task_id"]
        other_event_id = (await client.get(f"/v1/tasks/{second_task_id}/events")).json()["events"][0]["id"]

        stream = await client.get(
            f"/v1/tasks/{first_task_id}/stream",
            headers={"Last-Event-ID": other_event_id},
        )

    assert stream.status_code == 404


@pytest.mark.asyncio
async def test_sse_stream_delivers_live_events_after_restore():
    async with _client() as client:
        created = await client.post("/v1/tasks", json={"goal": "Demo", "allowed_tools": ["shell"]})
        task_id = created.json()["task_id"]
        first_id = (await client.get(f"/v1/tasks/{task_id}/events")).json()["events"][0]["id"]

        stream_task = asyncio.create_task(
            client.get(f"/v1/tasks/{task_id}/stream", headers={"Last-Event-ID": first_id})
        )
        await asyncio.sleep(0.02)
        completed = await client.post(f"/v1/tasks/{task_id}/run_once")
        completed.raise_for_status()
        stream = await asyncio.wait_for(stream_task, timeout=2)

        assert "event: task_completed" in stream.text


@pytest.mark.asyncio
async def test_create_task_rejects_blank_strings():
    async with _client() as client:
        blank_goal = await client.post("/v1/tasks", json={"goal": "   "})
        blank_tool = await client.post("/v1/tasks", json={"goal": "Demo", "allowed_tools": [""]})

    assert blank_goal.status_code == 422
    assert blank_tool.status_code == 422


@pytest.mark.asyncio
async def test_mvp_read_endpoints_are_available():
    async with _client() as client:
        created = await client.post("/v1/tasks", json={"goal": "Inspect"})
        task_id = created.json()["task_id"]

        task = await client.get(f"/v1/tasks/{task_id}")
        thinking = await client.get(f"/v1/tasks/{task_id}/thinking-summary")
        audit = await client.get(f"/v1/tasks/{task_id}/audit")
        artifacts = await client.get(f"/v1/tasks/{task_id}/artifacts")

    assert task.status_code == 200
    assert task.json()["task_id"] == task_id
    assert thinking.status_code == 200
    assert thinking.json()["deltas"] == []
    assert audit.status_code == 200
    assert audit.json()["hash_chain_valid"] is True
    assert audit.json()["events"]
    assert artifacts.status_code == 200
    assert artifacts.json()["artifacts"] == []


@pytest.mark.asyncio
async def test_run_once_executes_orchestrator_worker_and_auditor_pipeline():
    async with _client() as client:
        created = await client.post(
            "/v1/tasks",
            json={
                "goal": "Inspect repository status",
                "allowed_tools": ["git"],
                "acceptance_criteria": ["git status was inspected"],
            },
        )
        task_id = created.json()["task_id"]

        run = await client.post(f"/v1/tasks/{task_id}/run_once")
        events = (await client.get(f"/v1/tasks/{task_id}/events")).json()["events"]
        thinking = (await client.get(f"/v1/tasks/{task_id}/thinking-summary")).json()

    assert run.status_code == 200
    assert run.json()["status"] == "completed"
    event_types = [event["event_type"] for event in events]
    assert "planning_started" in event_types
    assert "worker_step_completed" in event_types
    assert "tool_execution_completed" in event_types
    assert "audit_verdict" in event_types
    assert event_types[-1] == "task_completed"
    assert thinking["deltas"]


@pytest.mark.asyncio
async def test_run_once_blocks_tasks_without_supported_worker_command():
    async with _client() as client:
        created = await client.post(
            "/v1/tasks",
            json={
                "goal": "Run unsupported tool",
                "allowed_tools": ["terraform"],
                "acceptance_criteria": ["terraform output inspected"],
            },
        )
        task_id = created.json()["task_id"]

        run = await client.post(f"/v1/tasks/{task_id}/run_once")
        events = (await client.get(f"/v1/tasks/{task_id}/events")).json()["events"]

    assert run.status_code == 200
    assert run.json()["status"] == "blocked"
    event_types = [event["event_type"] for event in events]
    assert "worker_step_blocked" in event_types
    assert event_types[-1] == "task_blocked"


@pytest.mark.asyncio
async def test_testing_app_removes_temp_database_on_lifespan_shutdown():
    app = create_app(testing=True)
    db_path = Path(app.state.testing_database_path)

    async with app.router.lifespan_context(app):
        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        async with client:
            created = await client.post("/v1/tasks", json={"goal": "Demo"})
            assert created.status_code == 201
        assert db_path.exists()

    assert not db_path.exists()
