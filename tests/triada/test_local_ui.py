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
    assert 'id="llm-config"' in response.text
    assert 'id="llm-clear-api-key"' in response.text


def test_local_swarm_ui_is_packaged():
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert Path("app/ui/__init__.py").is_file()
    assert project["tool"]["setuptools"]["package-data"]["app.ui"] == ["*.html"]
