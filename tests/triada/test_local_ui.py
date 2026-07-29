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
    assert 'id="contracts"' in response.text
    assert 'id="thinking"' in response.text
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
    assert 'id="contract-json"' in response.text
    assert 'id="save-contract"' in response.text
    assert 'id="refresh-contract-versions"' in response.text
    assert 'id="llm-config"' in response.text
    assert 'id="llm-clear-api-key"' in response.text
    assert 'id="create-task-form"' in response.text
    assert 'id="run-task"' in response.text
    assert 'id="event-feed"' in response.text
    assert 'id="event-auto-refresh"' in response.text
    assert 'id="event-auto-refresh" name="event-auto-refresh" type="checkbox" checked' in response.text
    assert 'id="refresh-events"' in response.text
    assert '"waiting_approval"' not in response.text.partition("const terminalStatuses = new Set(")[2].partition(");")[0]
    assert "/v1/tasks" in response.text
    assert "/v1/tasks?status=waiting_approval" in response.text
    assert "/approve" in response.text
    assert "/raw-reasoning/" in response.text
    assert "/v1/swarm/contracts" in response.text
    assert "/run_once" in response.text
    runs_view = response.text.partition('id="runs-view"')[2].partition('id="thinking-view"')[0]
    assert 'id="graph"' in runs_view
    assert 'id="events"' in runs_view
    load_task_body = response.text.partition("async function loadTask(taskId)")[2].partition("async function createTask")[0]
    assert "clearRawReasoningReveal();" in load_task_body


def test_local_swarm_ui_is_packaged():
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert Path("app/ui/__init__.py").is_file()
    assert project["tool"]["setuptools"]["package-data"]["app.ui"] == ["*.html"]
