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
async def test_swarm_capabilities_endpoint_exposes_role_boundaries():
    async with _client() as client:
        response = await client.get("/v1/swarm/capabilities")

    assert response.status_code == 200
    assert "execute_tools" not in response.json()["roles"]["auditor"]["allowed"]
    assert "issue_verdict" in response.json()["roles"]["auditor"]["allowed"]


@pytest.mark.asyncio
async def test_parameter_influence_is_append_only_and_retrievable():
    async with _client() as client:
        created = await client.post("/v1/tasks", json={"goal": "Measure parameter influence"})
        task_id = created.json()["task_id"]
        created_influence = await client.post(
            f"/v1/tasks/{task_id}/research/influence",
            json={
                "source_parameter": "parallelism",
                "target_parameter": "latency",
                "weight": -0.8,
                "reason": "Contention increases latency",
            },
        )
        fetched = await client.get(f"/v1/tasks/{task_id}/research/influence")

    assert created_influence.status_code == 201
    assert fetched.json()["summary"]["strong_count"] == 1


@pytest.mark.asyncio
async def test_task_budget_endpoint_exposes_configured_budget():
    async with _client() as client:
        created = await client.post(
            "/v1/tasks",
            json={
                "goal": "Bounded research",
                "resource_budget": {"max_parallel_branches": 2, "max_retries": 1, "max_tokens": 500},
            },
        )
        budget = await client.get(f"/v1/tasks/{created.json()['task_id']}/budget")

    assert budget.status_code == 200
    assert budget.json()["budget"] == {"max_parallel_branches": 2, "max_retries": 1, "max_tokens": 500}
    assert budget.json()["metrics"] == {"admitted_count": 0, "rejected_count": 0}


@pytest.mark.asyncio
async def test_task_memory_graph_stores_relations_and_conflicts():
    async with _client() as client:
        created = await client.post("/v1/tasks", json={"goal": "Build memory graph"})
        task_id = created.json()["task_id"]
        first = await client.post(
            f"/v1/tasks/{task_id}/memory",
            json={"kind": "decision", "title": "Use Postgres", "content": "Durable state"},
        )
        second = await client.post(
            f"/v1/tasks/{task_id}/memory",
            json={"kind": "constraint", "title": "No SQLite", "content": "Production uses Postgres"},
        )
        relation = await client.post(
            f"/v1/tasks/{task_id}/memory/relations",
            json={
                "source_memory_id": first.json()["memory_id"],
                "target_memory_id": second.json()["memory_id"],
                "relation": "contradicts",
                "reason": "Conflicting assumptions",
            },
        )
        graph = await client.get(f"/v1/tasks/{task_id}/memory/graph")

    assert relation.status_code == 201
    assert graph.status_code == 200
    assert graph.json()["summary"]["conflict_count"] == 1
    assert graph.json()["edges"][0]["relation"] == "contradicts"


@pytest.mark.asyncio
async def test_global_memory_graph_combines_relations_across_tasks():
    async with _client() as client:
        first_task = await client.post("/v1/tasks", json={"goal": "First research"})
        second_task = await client.post("/v1/tasks", json={"goal": "Second research"})
        first_note = await client.post(
            f"/v1/tasks/{first_task.json()['task_id']}/memory",
            json={"kind": "decision", "title": "Decision A", "content": "Use approach A"},
        )
        second_note = await client.post(
            f"/v1/tasks/{second_task.json()['task_id']}/memory",
            json={"kind": "observation", "title": "Finding B", "content": "Approach A works"},
        )
        await client.post(
            f"/v1/tasks/{first_task.json()['task_id']}/memory/relations",
            json={
                "source_memory_id": first_note.json()["memory_id"],
                "target_memory_id": second_note.json()["memory_id"],
                "relation": "supports",
            },
        )
        graph = await client.get("/v1/memory/graph")

    assert graph.status_code == 200
    assert graph.json()["summary"] == {"node_count": 2, "edge_count": 1, "conflict_count": 0}


@pytest.mark.asyncio
async def test_research_plan_is_append_only_and_retrievable():
    async with _client() as client:
        created = await client.post("/v1/tasks", json={"goal": "Research allocation"})
        task_id = created.json()["task_id"]
        response = await client.post(
            f"/v1/tasks/{task_id}/research",
            json={
                "question": "How should resources be allocated?",
                "parameter_catalog": ["parallelism", "latency"],
                "hypotheses": ["More parallelism improves coverage"],
                "depth": 2,
            },
        )
        fetched = await client.get(f"/v1/tasks/{task_id}/research")

    assert response.status_code == 201
    assert fetched.status_code == 200
    assert fetched.json()["plan"]["question"] == "How should resources be allocated?"
    assert fetched.json()["plan"]["unresolved_questions"]


@pytest.mark.asyncio
async def test_research_evidence_is_append_only_and_reports_coverage():
    async with _client() as client:
        created = await client.post("/v1/tasks", json={"goal": "Research evidence"})
        task_id = created.json()["task_id"]
        await client.post(
            f"/v1/tasks/{task_id}/research",
            json={
                "question": "Which strategy is safer?",
                "parameter_catalog": ["risk"],
                "hypotheses": ["Guardrails reduce risk"],
            },
        )
        evidence = await client.post(
            f"/v1/tasks/{task_id}/research/evidence",
            json={
                "kind": "experiment",
                "claim": "Guardrails reduced failures.",
                "content": "The deterministic test passed.",
                "supports_hypothesis": "Guardrails reduce risk",
                "confidence": 0.9,
            },
        )
        fetched = await client.get(f"/v1/tasks/{task_id}/research/evidence")

    assert evidence.status_code == 201
    assert fetched.status_code == 200
    assert fetched.json()["summary"]["coverage"] == 1.0
    assert fetched.json()["evidence"][0]["confidence"] == 0.9


@pytest.mark.asyncio
async def test_replay_creates_new_trace_and_waits_for_approval():
    async with _client() as client:
        created = await client.post("/v1/tasks", json={"goal": "Replay this task", "allowed_tools": ["echo"]})
        task_id = created.json()["task_id"]
        original_trace_id = created.json()["trace_id"]
        events = await client.get(f"/v1/tasks/{task_id}/events")
        event_id = events.json()["events"][0]["id"]

        replay = await client.post(
            f"/v1/tasks/{task_id}/replay",
            json={"from_event_id": event_id, "requested_by": "operator", "reason": "retry with new evidence"},
        )
        replay_task_id = replay.json()["task_id"]
        replay_events = await client.get(f"/v1/tasks/{replay_task_id}/events")
        before_source_event_count = len(events.json()["events"])
        approved = await client.post(f"/v1/tasks/{replay_task_id}/approve", json={"approved_by": "operator"})
        rerun = await client.post(f"/v1/tasks/{replay_task_id}/run_once")
        source_after = await client.get(f"/v1/tasks/{task_id}/events")

    assert replay.status_code == 201
    assert replay.json()["status"] == "waiting_approval"
    assert replay.json()["trace_id"] != original_trace_id
    assert approved.status_code == 200
    assert rerun.status_code == 200
    assert len(source_after.json()["events"]) == before_source_event_count
    replay_event_types = {event["event_type"] for event in replay_events.json()["events"]}
    assert replay_event_types == {"task_created", "replay_waiting_approval"}


@pytest.mark.asyncio
async def test_replay_rejects_event_from_another_trace():
    async with _client() as client:
        first = await client.post("/v1/tasks", json={"goal": "First"})
        second = await client.post("/v1/tasks", json={"goal": "Second"})
        first_event = (await client.get(f"/v1/tasks/{first.json()['task_id']}/events")).json()["events"][0]["id"]
        response = await client.post(
            f"/v1/tasks/{second.json()['task_id']}/replay",
            json={"from_event_id": first_event},
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_task_memory_notes_are_append_only_and_searchable():
    async with _client() as client:
        created = await client.post("/v1/tasks", json={"goal": "Build a research context"})
        task_id = created.json()["task_id"]
        added = await client.post(
            f"/v1/tasks/{task_id}/memory",
            json={
                "kind": "decision",
                "title": "Use bounded context",
                "content": "Keep research memory bounded and linked to evidence.",
                "tags": ["context", "quality"],
                "refs": ["event:1"],
            },
        )
        listed = await client.get(f"/v1/tasks/{task_id}/memory?q=evidence")
        audit = await client.get(f"/v1/tasks/{task_id}/audit")

    assert added.status_code == 201
    assert added.json()["kind"] == "decision"
    assert listed.status_code == 200
    assert len(listed.json()["notes"]) == 1
    assert listed.json()["notes"][0]["title"] == "Use bounded context"
    assert audit.status_code == 200
    assert audit.json()["hash_chain_valid"] is True


@pytest.mark.asyncio
async def test_task_memory_rejects_secret_content():
    async with _client() as client:
        created = await client.post("/v1/tasks", json={"goal": "Memory safety"})
        response = await client.post(
            f"/v1/tasks/{created.json()['task_id']}/memory",
            json={"kind": "observation", "title": "Unsafe", "content": "api_key=secret-value"},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_global_memory_search_retrieves_notes_across_tasks():
    async with _client() as client:
        first = await client.post("/v1/tasks", json={"goal": "First context"})
        second = await client.post("/v1/tasks", json={"goal": "Second context"})
        for task_id, title in (
            (first.json()["task_id"], "Research decision"),
            (second.json()["task_id"], "Architecture decision"),
        ):
            await client.post(
                f"/v1/tasks/{task_id}/memory",
                json={"kind": "decision", "title": title, "content": "Use evidence-backed context retrieval."},
            )
        response = await client.get("/v1/memory/search?q=evidence")

    assert response.status_code == 200
    assert {note["title"] for note in response.json()["notes"]} == {
        "Research decision",
        "Architecture decision",
    }


@pytest.mark.asyncio
async def test_task_events_can_be_filtered_without_sensitive_payloads():
    app = create_app(testing=True)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post(
                "/v1/tasks",
                json={
                    "goal": "Inspect repository status",
                    "allowed_tools": ["git"],
                    "acceptance_criteria": ["git status was inspected"],
                },
            )
            task_id = created.json()["task_id"]
            trace_id = created.json()["trace_id"]
            await client.post(f"/v1/tasks/{task_id}/run_once")
            await app.state.event_repository.append_event(
                event_type="model_reasoning_content_captured",
                trace_id=created.json()["trace_id"],
                task_id=task_id,
                agent_id="worker-1",
                payload={
                    "agent_role": "worker",
                    "raw_reasoning_content": "private reasoning must not be returned by public events",
                },
            )
            await app.state.event_repository.append_event(
                event_type="custom_debug_event",
                trace_id=created.json()["trace_id"],
                task_id=task_id,
                agent_id="worker-1",
                payload={
                    "raw_reasoning_content": "misplaced private reasoning must also be stripped",
                    "nested": {"raw_reasoning_content": "nested private reasoning"},
                },
            )

            tool_events = await client.get(f"/v1/tasks/{task_id}/events?event_type=tool_execution_completed")
            all_events = await client.get(f"/v1/tasks/{task_id}/events")
            worker_events = await client.get(f"/v1/tasks/{task_id}/events?agent_id=worker-1")
            trace_events = await client.get(f"/v1/tasks/{task_id}/events?trace_id={trace_id}")

            other = await client.post("/v1/tasks", json={"goal": "Other task"})
            mismatched_trace = await client.get(f"/v1/tasks/{task_id}/events?trace_id={other.json()['trace_id']}")

    assert tool_events.status_code == 200
    assert {event["event_type"] for event in tool_events.json()["events"]} == {"tool_execution_completed"}
    assert worker_events.status_code == 200
    assert worker_events.json()["events"]
    assert {event["agent_id"] for event in worker_events.json()["events"]} == {"worker-1"}
    assert trace_events.status_code == 200
    assert trace_events.json()["trace_id"] == trace_id
    assert mismatched_trace.status_code == 404

    payload = all_events.json()
    assert payload["raw_reasoning_refs"]
    reasoning_events = [event for event in payload["events"] if event["event_type"] == "model_reasoning_content_captured"]
    assert reasoning_events
    assert all("raw_reasoning_content" not in event["payload"] for event in reasoning_events)
    custom_events = [event for event in payload["events"] if event["event_type"] == "custom_debug_event"]
    assert custom_events
    assert "raw_reasoning_content" not in str(custom_events[0]["payload"])


@pytest.mark.asyncio
async def test_task_events_support_cursor_pagination():
    app = create_app(testing=True)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post("/v1/tasks", json={"goal": "Paginate events"})
            task_id = created.json()["task_id"]
            trace_id = created.json()["trace_id"]
            for index in range(5):
                await app.state.event_repository.append_event(
                    event_type="custom_page_event",
                    trace_id=trace_id,
                    task_id=task_id,
                    agent_id="tester",
                    payload={"index": index},
                )

            first_page = await client.get(f"/v1/tasks/{task_id}/events?event_type=custom_page_event&limit=2")
            cursor = first_page.json()["next_cursor"]
            second_page = await client.get(
                f"/v1/tasks/{task_id}/events?event_type=custom_page_event&limit=2&after_event_id={cursor}"
            )

    assert first_page.status_code == 200
    first_payload = first_page.json()
    assert len(first_payload["events"]) == 2
    assert first_payload["has_more"] is True
    assert first_payload["limit"] == 2
    assert first_payload["next_cursor"] == first_payload["events"][-1]["id"]

    assert second_page.status_code == 200
    second_payload = second_page.json()
    assert [event["payload"]["index"] for event in second_payload["events"]] == [2, 3]
    assert second_payload["has_more"] is True
    assert second_payload["next_cursor"] == second_payload["events"][-1]["id"]


@pytest.mark.asyncio
async def test_raw_reasoning_reveal_requires_explicit_acknowledgement():
    app = create_app(testing=True)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post("/v1/tasks", json={"goal": "Inspect"})
            task_id = created.json()["task_id"]
            event = await app.state.event_repository.append_event(
                event_type="model_reasoning_content_captured",
                trace_id=created.json()["trace_id"],
                task_id=task_id,
                agent_id="orchestrator",
                payload={"raw_reasoning_content": "private model reasoning"},
            )

            denied = await client.post(
                f"/v1/tasks/{task_id}/raw-reasoning/{event.id}/reveal",
                json={"acknowledge_sensitive": False},
            )
            revealed = await client.post(
                f"/v1/tasks/{task_id}/raw-reasoning/{event.id}/reveal",
                json={"acknowledge_sensitive": True, "requested_by": "operator"},
            )

    assert denied.status_code == 403
    assert revealed.status_code == 200
    assert revealed.json()["raw_reasoning_content"] == "private model reasoning"
    assert revealed.json()["agent_id"] == "orchestrator"


@pytest.mark.asyncio
async def test_list_recent_tasks_returns_latest_tasks_first():
    async with _client() as client:
        first = await client.post("/v1/tasks", json={"goal": "First task", "allowed_tools": ["shell"]})
        second = await client.post("/v1/tasks", json={"goal": "Second task", "allowed_tools": ["git"]})

        response = await client.get("/v1/tasks")

    assert first.status_code == 201
    assert second.status_code == 201
    assert response.status_code == 200
    tasks = response.json()["tasks"]
    assert [task["task_id"] for task in tasks[:2]] == [
        second.json()["task_id"],
        first.json()["task_id"],
    ]
    assert tasks[0]["goal"] == "Second task"
    assert tasks[0]["allowed_tools"] == ["git"]
    assert tasks[0]["status"] == "created"
    assert "created_at" in tasks[0]


@pytest.mark.asyncio
async def test_tasks_survive_app_restart(tmp_path):
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'triada.db'}"

    app = create_app(testing=True, database_url=database_url)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post(
                "/v1/tasks",
                json={
                    "goal": "Persist this task",
                    "allowed_tools": ["echo"],
                    "acceptance_criteria": ["task is visible after restart"],
                },
            )
            task_id = created.json()["task_id"]

    restarted = create_app(testing=True, database_url=database_url)
    async with restarted.router.lifespan_context(restarted):
        async with AsyncClient(transport=ASGITransport(app=restarted), base_url="http://test") as client:
            fetched = await client.get(f"/v1/tasks/{task_id}")
            listed = await client.get("/v1/tasks")

    assert fetched.status_code == 200
    assert fetched.json()["status"] == "created"
    assert listed.status_code == 200
    assert listed.json()["tasks"][0]["task_id"] == task_id
    assert listed.json()["tasks"][0]["goal"] == "Persist this task"


@pytest.mark.asyncio
async def test_pending_approval_plan_survives_app_restart(tmp_path):
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'triada.db'}"

    app = create_app(testing=True, database_url=database_url)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post(
                "/v1/tasks",
                json={
                    "goal": "write approved marker",
                    "allowed_tools": ["write_file"],
                    "acceptance_criteria": ["file is written only after approval"],
                },
            )
            task_id = created.json()["task_id"]
            first_run = await client.post(f"/v1/tasks/{task_id}/run_once")

    assert first_run.status_code == 200
    assert first_run.json()["status"] == "waiting_approval"

    restarted = create_app(testing=True, database_url=database_url)
    async with restarted.router.lifespan_context(restarted):
        async with AsyncClient(transport=ASGITransport(app=restarted), base_url="http://test") as client:
            waiting = await client.get("/v1/tasks?status=waiting_approval")
            approved = await client.post(f"/v1/tasks/{task_id}/approve", json={"approved_by": "operator"})
            completed = await client.post(f"/v1/tasks/{task_id}/run_once")
            events = (await client.get(f"/v1/tasks/{task_id}/events")).json()["events"]

    assert waiting.status_code == 200
    assert waiting.json()["tasks"][0]["task_id"] == task_id
    assert approved.status_code == 200
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    event_types = [event["event_type"] for event in events]
    assert "planning_reused" in event_types


@pytest.mark.asyncio
async def test_list_recent_tasks_can_filter_waiting_approval():
    async with _client() as client:
        waiting = await client.post(
            "/v1/tasks",
            json={
                "goal": "Write repository file after approval",
                "allowed_tools": ["shell"],
                "acceptance_criteria": ["change approved"],
            },
        )
        waiting_task_id = waiting.json()["task_id"]
        await client.post(f"/v1/tasks/{waiting_task_id}/run_once")
        completed = await client.post(
            "/v1/tasks",
            json={
                "goal": "Inspect repository status",
                "allowed_tools": ["git"],
                "acceptance_criteria": ["git status inspected"],
            },
        )
        await client.post(f"/v1/tasks/{completed.json()['task_id']}/run_once")

        response = await client.get("/v1/tasks?status=waiting_approval")

    assert response.status_code == 200
    tasks = response.json()["tasks"]
    assert [task["task_id"] for task in tasks] == [waiting_task_id]
    assert tasks[0]["status"] == "waiting_approval"


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
async def test_sse_stream_strips_raw_reasoning_content_recursively():
    app = create_app(testing=True)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post("/v1/tasks", json={"goal": "Inspect"})
            task_id = created.json()["task_id"]
            first_id = (await client.get(f"/v1/tasks/{task_id}/events")).json()["events"][0]["id"]
            await app.state.event_repository.append_event(
                event_type="custom_debug_event",
                trace_id=created.json()["trace_id"],
                task_id=task_id,
                agent_id="worker-1",
                payload={
                    "raw_reasoning_content": "private top-level",
                    "nested": {"raw_reasoning_content": "private nested"},
                },
            )

            stream = await client.get(
                f"/v1/tasks/{task_id}/stream",
                headers={"Last-Event-ID": first_id},
            )

    assert stream.status_code == 200
    assert "raw_reasoning_content" not in stream.text
    assert "private nested" not in stream.text


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
async def test_demo_templates_are_available_for_local_ui():
    async with _client() as client:
        response = await client.get("/v1/demo/templates")

    assert response.status_code == 200
    templates = response.json()["templates"]
    template_ids = {template["id"] for template in templates}
    assert {"git_status", "repo_health_review", "thinking_capture", "approval_gate"}.issubset(template_ids)
    repo_health = next(template for template in templates if template["id"] == "repo_health_review")
    assert repo_health["allowed_tools"] == ["git", "rg", "sed"]
    for template in templates:
        assert template["goal"]
        assert isinstance(template["allowed_tools"], list)
        assert isinstance(template["acceptance_criteria"], list)


@pytest.mark.asyncio
async def test_demo_run_executes_template_and_returns_observability_payload():
    async with _client() as client:
        response = await client.post("/v1/demo/run", json={"template_id": "git_status"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["template_id"] == "git_status"
    assert payload["task"]["status"] == "completed"
    assert payload["actions"] == ["created", "run_once"]
    assert payload["thinking"]["deltas"]
    assert payload["graph"]["nodes"]
    assert payload["graph"]["edges"]
    assert payload["events"]["events"]
    event_types = [event["event_type"] for event in payload["events"]["events"]]
    assert "tool_execution_completed" in event_types
    assert all("raw_reasoning_content" not in str(event["payload"]) for event in payload["events"]["events"])


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
