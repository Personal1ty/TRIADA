from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

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
async def test_get_swarm_contract():
    async with _client() as client:
        response = await client.get("/v1/swarm/contract")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "1.0"
    assert len(payload["worker_auditor_pairs"]) >= 3
    assert any(route["reason"] == "deliver_human_packet" for route in payload["route_map"])


@pytest.mark.asyncio
async def test_get_task_route_graph():
    async with _client() as client:
        created = await client.post(
            "/v1/tasks",
            json={
                "goal": "inspect repository status",
                "allowed_tools": ["git"],
                "acceptance_criteria": ["return git status"],
            },
        )
        task_id = created.json()["task_id"]

        await client.post(f"/v1/tasks/{task_id}/run_once")
        response = await client.get(f"/v1/tasks/{task_id}/swarm-graph")

    assert response.status_code == 200
    payload = response.json()
    assert payload["nodes"]
    assert payload["edges"]

    reasons = {edge["reason"] for edge in payload["edges"]}
    assert {
        "assign_step",
        "submit_evidence",
        "escalate_verdict",
        "return_final_gate",
        "deliver_human_packet",
    }.issubset(reasons)
    for edge in payload["edges"]:
        assert edge["input_contract"].endswith("@1.0")
        assert edge["output_contract"].endswith("@1.0")
