import json
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest

from app.events.models import ThinkingSummaryDelta
from app.llm.fake import FakeLLMProvider
from app.llm.openai_compatible import OpenAICompatibleProvider
from app.schemas.enums import AgentRole, DeltaSource


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
@pytest.mark.parametrize("schema_name", ["plan", "worker_result", "audit_verdict", "default"])
async def test_fake_llm_thinking_summary_deltas_are_public_safe(schema_name):
    provider = FakeLLMProvider()

    result = await provider.complete_json("plan a task", schema_name=schema_name)

    ThinkingSummaryDelta(
        schema_version="1.0",
        event_id=UUID("00000000-0000-0000-0000-000000000001"),
        trace_id=UUID("00000000-0000-0000-0000-000000000002"),
        task_id=UUID("00000000-0000-0000-0000-000000000003"),
        span_id=UUID("00000000-0000-0000-0000-000000000004"),
        agent_id="fake-llm",
        agent_role=AgentRole.ORCHESTRATOR,
        source=DeltaSource.MODEL,
        sequence=1,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        **result["thinking_summary_delta"],
    )


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
    assert body["stream"] is True


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


@pytest.mark.asyncio
async def test_openai_provider_parses_streaming_lines_and_marks_reasoning_summary():
    seen_request = None
    content_payload = {
        "thinking_summary_delta": {
            "stage": "planning",
            "action": "draft_plan",
            "summary": "Prepared a public plan summary.",
            "observations": ["streamed"],
            "next_step": "dispatch_worker",
            "confidence": 0.8,
        },
        "answer": {"steps": [{"id": "step-1", "description": "Inspect repository"}]},
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_request
        seen_request = request
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text="\n".join(
                [
                    'data: {"choices":[{"delta":{"reasoning_content":"private chain text must not persist"}}]}',
                    f'data: {json.dumps({"choices": [{"delta": {"content": json.dumps(content_payload)}}]})}',
                    "data: [DONE]",
                    "",
                ]
            ),
        )

    provider = OpenAICompatibleProvider(
        base_url="https://llm.example.test",
        api_key=None,
        model="corp-coder",
        transport=httpx.MockTransport(handler),
    )

    result = await provider.complete_json("hello", schema_name="plan")

    assert result["answer"] == content_payload["answer"]
    assert result["thinking_summary_delta"]["summary"] == "Prepared a public plan summary."
    assert result["model_message"]["has_reasoning_content"] is True
    assert "private chain text" not in json.dumps(result)
    assert seen_request is not None
    assert json.loads(seen_request.content)["stream"] is True


@pytest.mark.asyncio
async def test_openai_provider_parses_jsonl_stream_without_sse_prefix():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/x-ndjson"},
            text="\n".join(
                [
                    json.dumps(
                        {
                            "choices": [
                                {
                                    "delta": {
                                        "content": json.dumps(
                                            {"answer": {"ok": True}}
                                        )
                                    }
                                }
                            ]
                        }
                    ),
                    "[DONE]",
                    "",
                ]
            ),
        )

    provider = OpenAICompatibleProvider(
        base_url="https://llm.example.test",
        api_key=None,
        model="corp-coder",
        transport=httpx.MockTransport(handler),
    )

    assert await provider.complete_json("hello", schema_name="plan") == {"answer": {"ok": True}}
