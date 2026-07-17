import json

import httpx
import pytest

from app.llm.fake import FakeLLMProvider
from app.llm.openai_compatible import OpenAICompatibleProvider


def assert_structured_thinking_summary(value):
    assert isinstance(value, dict)
    assert {
        "stage",
        "action",
        "summary",
        "observations",
        "next_step",
        "confidence",
    } <= value.keys()


@pytest.mark.asyncio
async def test_fake_llm_is_deterministic():
    provider = FakeLLMProvider()
    first = await provider.complete_json("plan a task", schema_name="plan")
    second = await provider.complete_json("plan a task", schema_name="plan")
    assert first == second
    assert_structured_thinking_summary(first["thinking_summary_delta"])
    assert "answer" in first


@pytest.mark.asyncio
async def test_openai_provider_requires_base_url_for_real_calls():
    provider = OpenAICompatibleProvider(base_url=None, api_key=None, model="corp-coder")
    with pytest.raises(RuntimeError, match="LLM_BASE_URL"):
        await provider.complete_json("hello", schema_name="plan")


@pytest.mark.asyncio
async def test_openai_provider_error_does_not_leak_api_key():
    provider = OpenAICompatibleProvider(
        base_url=None,
        api_key="sk-secret-token",
        model="corp-coder",
    )
    with pytest.raises(RuntimeError) as exc:
        await provider.complete_json("hello", schema_name="plan")
    assert "sk-secret-token" not in str(exc.value)


@pytest.mark.asyncio
async def test_openai_provider_success_path_parses_json_and_sends_request():
    seen_request = None
    thinking_summary_delta = {
        "stage": "planning",
        "action": "parse",
        "summary": "parsed response",
        "observations": ["fixture"],
        "next_step": "return",
        "confidence": 0.9,
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_request
        seen_request = request
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "thinking_summary_delta": thinking_summary_delta,
                                    "answer": {"ok": True},
                                }
                            )
                        }
                    }
                ]
            },
        )

    provider = OpenAICompatibleProvider(
        base_url="https://llm.example.test/",
        api_key="sk-secret-token",
        model="corp-coder",
        transport=httpx.MockTransport(handler),
    )

    result = await provider.complete_json("hello", schema_name="plan")

    assert result == {
        "thinking_summary_delta": thinking_summary_delta,
        "answer": {"ok": True},
    }
    assert seen_request is not None
    assert str(seen_request.url) == "https://llm.example.test/chat/completions"
    assert seen_request.headers["authorization"] == "Bearer sk-secret-token"
    body = json.loads(seen_request.content)
    assert body["model"] == "corp-coder"
    assert body["messages"] == [{"role": "user", "content": "hello"}]


@pytest.mark.asyncio
async def test_openai_provider_http_error_does_not_leak_api_key_or_cause():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="upstream failed sk-secret-token")

    provider = OpenAICompatibleProvider(
        base_url="https://llm.example.test",
        api_key="sk-secret-token",
        model="corp-coder",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(RuntimeError) as exc:
        await provider.complete_json("hello", schema_name="plan")

    assert "sk-secret-token" not in str(exc.value)
    assert exc.value.__cause__ is None


@pytest.mark.asyncio
async def test_openai_provider_rejects_non_json_without_leaking_api_key_or_cause():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "not json sk-secret-token"}}]},
        )

    provider = OpenAICompatibleProvider(
        base_url="https://llm.example.test",
        api_key="sk-secret-token",
        model="corp-coder",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(RuntimeError) as exc:
        await provider.complete_json("hello", schema_name="plan")

    assert "non-JSON" in str(exc.value)
    assert "sk-secret-token" not in str(exc.value)
    assert exc.value.__cause__ is None


@pytest.mark.asyncio
async def test_openai_provider_omits_authorization_without_api_key():
    seen_request = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_request
        seen_request = request
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "{\"answer\": true}"}}]},
        )

    provider = OpenAICompatibleProvider(
        base_url="https://llm.example.test",
        api_key=None,
        model="corp-coder",
        transport=httpx.MockTransport(handler),
    )

    assert await provider.complete_json("hello", schema_name="plan") == {"answer": True}
    assert seen_request is not None
    assert "authorization" not in seen_request.headers
