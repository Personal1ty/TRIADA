from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@asynccontextmanager
async def _client(*, database_url: str | None = None) -> AsyncIterator[AsyncClient]:
    app = create_app(testing=True, database_url=database_url)
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
async def test_save_and_load_runtime_swarm_contract_version():
    async with _client() as client:
        current = (await client.get("/v1/swarm/contract")).json()
        current["contract_version"] = "local-test"
        current["topology"]["chief_auditor"]["strict_mode"] = True

        saved = await client.post("/v1/swarm/contract", json=current)
        versions = await client.get("/v1/swarm/contracts")
        loaded = await client.get("/v1/swarm/contract?version=local-test")

    assert saved.status_code == 200
    assert saved.json()["contract_version"] == "local-test"
    assert loaded.status_code == 200
    assert loaded.json()["topology"]["chief_auditor"]["strict_mode"] is True
    assert "local-test" in versions.json()["versions"]


@pytest.mark.asyncio
async def test_saved_swarm_contract_versions_survive_app_restart(tmp_path):
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'triada.db'}"

    async with _client(database_url=database_url) as client:
        current = (await client.get("/v1/swarm/contract")).json()
        current["contract_version"] = "persisted-test"
        current["topology"]["chief_auditor"]["strict_mode"] = True

        saved = await client.post("/v1/swarm/contract", json=current)

    assert saved.status_code == 200

    async with _client(database_url=database_url) as client:
        versions = await client.get("/v1/swarm/contracts")
        loaded = await client.get("/v1/swarm/contract?version=persisted-test")

    assert versions.status_code == 200
    assert versions.json()["active_version"] == "persisted-test"
    assert "persisted-test" in versions.json()["versions"]
    assert loaded.status_code == 200
    assert loaded.json()["topology"]["chief_auditor"]["strict_mode"] is True


@pytest.mark.asyncio
async def test_swarm_contract_versions_include_metadata():
    async with _client() as client:
        current = (await client.get("/v1/swarm/contract")).json()
        current["contract_version"] = "metadata-test"
        current["__metadata"] = {
            "author": "operator",
            "notes": "Test notes",
            "change_reason": "Validate metadata storage",
        }

        saved = await client.post("/v1/swarm/contract", json=current)
        versions = await client.get("/v1/swarm/contracts")

    assert saved.status_code == 200
    payload = versions.json()
    details = {item["contract_version"]: item for item in payload["version_details"]}
    assert details["metadata-test"]["metadata"]["author"] == "operator"
    assert details["metadata-test"]["metadata"]["notes"] == "Test notes"
    assert details["metadata-test"]["metadata"]["change_reason"] == "Validate metadata storage"
    assert details["metadata-test"]["is_active"] is True


@pytest.mark.asyncio
async def test_contract_diff_returns_changed_paths_between_versions():
    async with _client() as client:
        current = (await client.get("/v1/swarm/contract")).json()
        first = dict(current)
        first["contract_version"] = "diff-before"
        await client.post("/v1/swarm/contract", json=first)

        second = dict(current)
        second["contract_version"] = "diff-after"
        second["topology"] = dict(current["topology"])
        second["topology"]["chief_auditor"] = dict(current["topology"]["chief_auditor"])
        second["topology"]["chief_auditor"]["strict_mode"] = True
        await client.post("/v1/swarm/contract", json=second)
        response = await client.get(
            "/v1/swarm/contract/diff?from_version=diff-before&to_version=diff-after"
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["from_version"] == "diff-before"
    assert payload["to_version"] == "diff-after"
    assert {
        change["path"] for change in payload["changes"]
    } == {"topology.chief_auditor.strict_mode"}
    assert payload["changes"][0]["before"] is False
    assert payload["changes"][0]["after"] is True


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
    assert payload["summary"]["edge_count"] == len(payload["edges"])
    assert payload["summary"]["node_count"] == len(payload["nodes"])
    assert "assign_step" in payload["summary"]["route_reasons"]

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
        assert edge["label"].startswith(f"{edge['sequence']}. ")
        assert edge["status"] == "selected"

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["orchestrator"]["role"] == "orchestrator"
    assert nodes["orchestrator"]["label"] == "Orchestrator"
    assert nodes["worker-1"]["role"] == "worker"
    assert nodes["worker-1"]["pair_id"] == "worker-1:auditor-1"
    assert nodes["auditor-1"]["role"] == "auditor"
    assert nodes["auditor-1"]["pair_id"] == "worker-1:auditor-1"
    assert nodes["chief-auditor"]["role"] == "chief_auditor"
    assert nodes["human"]["label"] == "Human"
    assert nodes["orchestrator"]["outgoing_count"] >= 1

    assigned_edge = next(edge for edge in payload["edges"] if edge["reason"] == "assign_step")
    audit_edge = next(edge for edge in payload["edges"] if edge["reason"] == "submit_evidence")
    assert assigned_edge["source"] == "orchestrator"
    assert assigned_edge["target"] == "worker-1"
    assert audit_edge["source"] == "worker-1"
    assert audit_edge["target"] == "auditor-1"


@pytest.mark.asyncio
async def test_get_task_inspector_returns_phase_metrics_and_agent_states():
    async with _client() as client:
        created = await client.post(
            "/v1/tasks",
            json={"goal": "inspect repository status", "allowed_tools": ["git"]},
        )
        task_id = created.json()["task_id"]
        await client.post(f"/v1/tasks/{task_id}/run_once")
        response = await client.get(f"/v1/tasks/{task_id}/inspector")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["inspector"]["phase"] == "completed"
    assert payload["inspector"]["metrics"]["route_count"] == 5
    assert {agent["agent_id"] for agent in payload["inspector"]["agents"]} >= {
        "orchestrator",
        "worker-1",
        "auditor-1",
        "chief-auditor",
    }


@pytest.mark.asyncio
async def test_get_task_quality_returns_evidence_and_audit_metrics():
    async with _client() as client:
        created = await client.post(
            "/v1/tasks",
            json={"goal": "inspect repository status", "allowed_tools": ["git"]},
        )
        task_id = created.json()["task_id"]
        await client.post(f"/v1/tasks/{task_id}/run_once")
        response = await client.get(f"/v1/tasks/{task_id}/quality")

    assert response.status_code == 200
    payload = response.json()
    assert payload["quality"]["metrics"]["evidence_coverage"] == 1.0
    assert payload["quality"]["metrics"]["audit_pass_rate"] == 1.0
    assert payload["quality"]["metrics"]["correction_count"] == 0
    assert payload["quality"]["replay_points"] == []


@pytest.mark.asyncio
async def test_get_task_checkpoints_returns_safe_resume_refs():
    async with _client() as client:
        created = await client.post(
            "/v1/tasks",
            json={"goal": "inspect repository status", "allowed_tools": ["git"]},
        )
        task_id = created.json()["task_id"]
        await client.post(f"/v1/tasks/{task_id}/run_once")
        response = await client.get(f"/v1/tasks/{task_id}/checkpoints")

    assert response.status_code == 200
    checkpoints = response.json()["checkpoints"]
    assert checkpoints
    assert all("raw_reasoning_content" not in str(checkpoint) for checkpoint in checkpoints)
    assert checkpoints[-1]["phase"] == "completed"
    assert checkpoints[-1]["resumable"] is False


@pytest.mark.asyncio
async def test_task_route_graph_survives_app_restart(tmp_path):
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'triada.db'}"

    async with _client(database_url=database_url) as client:
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

    async with _client(database_url=database_url) as client:
        task = await client.get(f"/v1/tasks/{task_id}")
        graph = await client.get(f"/v1/tasks/{task_id}/swarm-graph")

    assert task.status_code == 200
    assert graph.status_code == 200
    assert graph.json()["nodes"]
    assert graph.json()["edges"]
