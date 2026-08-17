from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
import tomllib

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
async def test_get_local_swarm_ui():
    async with _client() as client:
        response = await client.get("/ui")

    assert response.status_code == 200
    assert "TRIADA Swarm" in response.text
    assert "/v1/swarm/contract" in response.text
    assert "/v1/llm/config" in response.text
    assert "/v1/llm/test" in response.text
    assert 'id="graph"' in response.text
    assert 'id="run-observatory"' in response.text
    assert 'id="observatory-timeline"' in response.text
    assert 'id="observatory-inspector"' in response.text
    assert 'id="observatory-evidence"' in response.text
    assert 'id="observatory-pass-rate"' in response.text
    assert 'id="observatory-replay"' in response.text
    assert 'id="observatory-checkpoints"' in response.text
    assert 'id="observatory-checkpoint-list"' in response.text
    assert 'class="replay-task"' in response.text
    assert "/replay" in response.text
    assert "/v1/tasks/${encodeURIComponent(currentTaskId)}/quality" in response.text
    assert "/v1/tasks/${encodeURIComponent(currentTaskId)}/checkpoints" in response.text
    assert "/v1/tasks/${encodeURIComponent(currentTaskId)}/inspector" in response.text
    assert "renderRunObservatory" in response.text
    assert 'id="graph-summary"' in response.text
    assert 'id="graph-route-list"' in response.text
    assert 'class="graph-node-meta"' in response.text
    assert 'id="contracts"' in response.text
    assert 'id="thinking"' in response.text
    assert 'id="memory"' in response.text
    assert 'id="memory-query"' in response.text
    assert 'id="search-memory"' in response.text
    assert 'id="global-memory"' in response.text
    assert 'id="observatory-memory-backend"' in response.text
    assert 'id="observatory-budget"' in response.text
    assert 'id="memory-graph"' in response.text
    assert "/memory/graph" in response.text
    assert 'id="global-memory-graph-status"' in response.text
    assert 'id="research-plan"' in response.text
    assert 'id="research-evidence"' in response.text
    assert "/research" in response.text
    assert 'id="search-global-memory"' in response.text
    assert "/v1/memory/search?q=" in response.text
    assert "/v1/tasks/${encodeURIComponent(taskId)}/memory" in response.text
    assert 'id="runs-tab"' in response.text
    assert 'id="thinking-tab"' in response.text
    assert 'id="raw-reasoning-tab"' in response.text
    assert 'id="contracts-tab"' in response.text
    assert 'id="approvals-tab"' in response.text
    assert 'id="approval-queue"' in response.text
    assert 'id="refresh-approvals"' in response.text
    assert 'class="approve-task"' in response.text
    assert 'id="raw-reasoning-locked"' in response.text
    assert 'id="raw-reasoning-ack"' in response.text
    assert 'id="raw-reasoning-refs"' in response.text
    assert 'class="reveal-raw-reasoning"' in response.text
    assert 'id="contract-version-select"' in response.text
    assert 'id="contract-diff-from"' in response.text
    assert 'id="contract-diff-to"' in response.text
    assert 'id="compare-contracts"' in response.text
    assert "contract/diff?from_version=" in response.text
    assert 'id="contract-version"' in response.text
    assert 'id="contract-author"' in response.text
    assert 'id="contract-notes"' in response.text
    assert 'id="contract-change-reason"' in response.text
    assert 'id="contract-validation-errors"' in response.text
    assert 'id="chief-auditor-id"' in response.text
    assert 'id="chief-auditor-strict"' in response.text
    assert 'id="scaling-default-pairs"' in response.text
    assert 'id="scaling-min-pairs"' in response.text
    assert 'id="scaling-max-pairs"' in response.text
    assert 'id="worker-pair-editor"' in response.text
    assert 'id="add-worker-pair"' in response.text
    assert 'id="route-map-editor"' in response.text
    assert 'id="add-route-map-entry"' in response.text
    assert 'id="sync-contract-json"' in response.text
    assert 'id="contract-json"' in response.text
    assert 'id="contract-bodies"' in response.text
    assert 'class="contract-body-card"' in response.text
    assert 'class="contracts-layout"' in response.text
    assert 'class="contract-editor-column"' in response.text
    assert 'class="contract-inspector-column"' in response.text
    assert "@media (min-width: 1280px)" in response.text
    assert "max-width: 100%;" in response.text
    assert "width: min(440px, 48vw)" not in response.text
    assert "renderContractBodies" in response.text
    assert 'id="save-contract"' in response.text
    assert 'id="refresh-contract-versions"' in response.text
    assert 'id="llm-config"' in response.text
    assert 'id="llm-clear-api-key"' in response.text
    assert 'id="create-task-form"' in response.text
    assert 'id="demo-template-select"' in response.text
    assert 'id="load-demo-template"' in response.text
    assert 'id="run-demo-flow"' in response.text
    assert 'id="run-task"' in response.text
    assert 'id="event-feed"' in response.text
    assert 'id="event-auto-refresh"' in response.text
    assert 'id="event-auto-refresh" name="event-auto-refresh" type="checkbox" checked' in response.text
    assert 'id="refresh-events"' in response.text
    assert 'id="load-more-events"' in response.text
    assert "after_event_id" in response.text
    assert '"waiting_approval"' not in response.text.partition("const terminalStatuses = new Set(")[2].partition(");")[0]
    assert "/v1/tasks" in response.text
    assert "/v1/tasks?status=waiting_approval" in response.text
    assert "/v1/demo/templates" in response.text
    assert "/v1/demo/run" in response.text
    assert "/approve" in response.text
    assert "/raw-reasoning/" in response.text
    assert 'window.location.protocol === "file:"' in response.text
    assert "http://127.0.0.1:8000/ui" in response.text
    assert "/v1/swarm/contracts" in response.text
    assert "/run_once" in response.text
    runs_view = response.text.partition('id="runs-view"')[2].partition('id="thinking-view"')[0]
    assert 'id="graph"' in runs_view
    assert 'id="events"' in runs_view
    load_task_body = response.text.partition("async function loadTask(taskId)")[2].partition("async function createTask")[0]
    assert "clearRawReasoningReveal();" in load_task_body
    assert "validateContractForm" in response.text
    assert "routesFromEditor" in response.text
    assert "runSelectedDemoFlow" in response.text
    assert "graph-lane-label" in response.text
    assert "node-worker" in response.text


def test_local_swarm_ui_is_packaged():
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert Path("app/ui/__init__.py").is_file()
    assert project["tool"]["setuptools"]["package-data"]["app.ui"] == ["*.html"]
