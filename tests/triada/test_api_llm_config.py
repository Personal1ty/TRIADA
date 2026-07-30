from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


class RecordingProvider:
    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.schema_names: list[str] = []

    async def complete_json(self, prompt: str, *, schema_name: str):
        self.prompts.append(prompt)
        self.schema_names.append(schema_name)
        return {"answer": {"ok": True}}


@asynccontextmanager
async def _client() -> AsyncIterator[AsyncClient]:
    app = create_app(testing=True)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client


@pytest.mark.asyncio
async def test_get_llm_config_returns_public_config_without_secret():
    async with _client() as client:
        response = await client.get("/v1/llm/config")

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "fake"
    assert payload["model"] == "fake-devops-model"
    assert payload["has_api_key"] is False
    assert "api_key" not in payload
    assert "token" not in payload


@pytest.mark.asyncio
async def test_post_llm_config_persists_secret_but_returns_only_has_api_key():
    async with _client() as client:
        response = await client.post(
            "/v1/llm/config",
            json={
                "provider": "openai-compatible",
                "base_url": "https://deepseek.example/v1",
                "model": "deepseek-reasoner",
                "api_key": "sk-runtime-secret",
            },
        )
        fetched = await client.get("/v1/llm/config")

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "openai-compatible"
    assert payload["base_url"] == "https://deepseek.example/v1"
    assert payload["model"] == "deepseek-reasoner"
    assert payload["has_api_key"] is True
    assert "sk-runtime-secret" not in str(payload)
    assert "api_key" not in payload
    assert fetched.json() == payload


@pytest.mark.asyncio
async def test_post_llm_config_preserves_saved_api_key_when_field_is_omitted():
    async with _client() as client:
        await client.post(
            "/v1/llm/config",
            json={
                "provider": "openai-compatible",
                "base_url": "https://deepseek.example/v1",
                "model": "deepseek-reasoner",
                "api_key": "sk-runtime-secret",
            },
        )
        response = await client.post(
            "/v1/llm/config",
            json={
                "provider": "openai-compatible",
                "base_url": "https://deepseek.example/v2",
                "model": "deepseek-reasoner-v2",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["base_url"] == "https://deepseek.example/v2"
    assert payload["model"] == "deepseek-reasoner-v2"
    assert payload["has_api_key"] is True
    assert "sk-runtime-secret" not in str(payload)


@pytest.mark.asyncio
@pytest.mark.parametrize("api_key_value", [None, ""])
async def test_post_llm_config_preserves_saved_api_key_when_value_is_null_or_blank(api_key_value):
    async with _client() as client:
        await client.post(
            "/v1/llm/config",
            json={
                "provider": "openai-compatible",
                "base_url": "https://deepseek.example/v1",
                "model": "deepseek-reasoner",
                "api_key": "sk-runtime-secret",
            },
        )
        response = await client.post(
            "/v1/llm/config",
            json={
                "provider": "openai-compatible",
                "base_url": "https://deepseek.example/v2",
                "model": "deepseek-reasoner-v2",
                "api_key": api_key_value,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["base_url"] == "https://deepseek.example/v2"
    assert payload["model"] == "deepseek-reasoner-v2"
    assert payload["has_api_key"] is True
    assert "sk-runtime-secret" not in str(payload)


@pytest.mark.asyncio
async def test_post_llm_config_clears_saved_api_key_only_when_requested():
    async with _client() as client:
        await client.post(
            "/v1/llm/config",
            json={
                "provider": "openai-compatible",
                "base_url": "https://deepseek.example/v1",
                "model": "deepseek-reasoner",
                "api_key": "sk-runtime-secret",
            },
        )
        response = await client.post(
            "/v1/llm/config",
            json={
                "provider": "openai-compatible",
                "base_url": "https://deepseek.example/v1",
                "model": "deepseek-reasoner",
                "clear_api_key": True,
            },
        )

    assert response.status_code == 200
    assert response.json()["has_api_key"] is False


@pytest.mark.asyncio
async def test_llm_test_endpoint_reports_configured_provider_without_leaking_secret():
    async with _client() as client:
        await client.post(
            "/v1/llm/config",
            json={
                "provider": "openai-compatible",
                "base_url": None,
                "model": "corp-coder",
                "api_key": "sk-runtime-secret",
            },
        )
        response = await client.post("/v1/llm/test")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["provider"] == "openai-compatible"
    assert payload["model"] == "corp-coder"
    assert "sk-runtime-secret" not in str(payload)


@pytest.mark.asyncio
async def test_llm_test_endpoint_requests_json_connectivity_response():
    app = create_app(testing=True)
    provider = RecordingProvider()
    async with app.router.lifespan_context(app):
        app.state.execution_engine._build_llm_provider = lambda: provider
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/v1/llm/test")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert provider.schema_names == ["plan"]
    assert "Return only JSON" in provider.prompts[0]
    assert '"answer"' in provider.prompts[0]
