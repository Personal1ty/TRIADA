import json
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest

from app.events.models import ThinkingSummaryDelta
from app.llm.codex_bridge import CodexBridgeProvider
from app.llm.fake import FakeLLMProvider
from app.llm.openai_compatible import OpenAICompatibleProvider
from app.llm.openai_responses import OpenAIResponsesProvider
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
@pytest.mark.parametrize("schema_name", ["plan", "worker_result", "audit_verdict"])
async def test_codex_bridge_provider_returns_persistable_reasoning(schema_name):
    provider = CodexBridgeProvider()

    result = await provider.complete_json("Проверь git status", schema_name=schema_name)

    assert_structured_thinking_summary(result["thinking_summary_delta"])
    assert result["model_message"] == {
        "has_reasoning_content": True,
        "reasoning_content_stored": True,
        "reasoning_source": "codex_bridge",
    }
    assert "Codex bridge" in result["raw_reasoning_content"]


@pytest.mark.asyncio
async def test_codex_bridge_provider_plans_safe_git_status_step():
    provider = CodexBridgeProvider()

    result = await provider.complete_json("Проверь git status", schema_name="plan")

    assert result["answer"]["steps"] == [
        {
            "id": "step-1",
            "title": "Inspect git status",
            "description": "Run git status and summarize repository state.",
            "allowed_tools": ["git"],
        }
    ]


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
async def test_openai_provider_extracts_json_object_from_wrapped_content():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                "<think>private planning text</think>\n"
                                "```json\n"
                                "{\"thinking_summary_delta\":{\"stage\":\"planning\",\"action\":\"draft\","
                                "\"summary\":\"planned\",\"observations\":[],\"next_step\":\"execute\","
                                "\"confidence\":0.8},\"answer\":{\"steps\":[{\"id\":\"step-1\","
                                "\"description\":\"Use echo\",\"allowed_tools\":[\"echo\"]}]}}\n"
                                "```"
                            )
                        }
                    }
                ]
            },
        )

    provider = OpenAICompatibleProvider(
        base_url="https://llm.example.test",
        api_key=None,
        model="corp-coder",
        transport=httpx.MockTransport(handler),
    )

    result = await provider.complete_json("hello", schema_name="plan")

    assert result["answer"]["steps"][0]["allowed_tools"] == ["echo"]
    assert result["thinking_summary_delta"]["summary"] == "planned"


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
                    'data: {"choices":[{"delta":{"reasoning_content":"private chain text should persist as sensitive data"}}]}',
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
    assert result["raw_reasoning_content"] == "private chain text should persist as sensitive data"
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


@pytest.mark.asyncio
async def test_openai_responses_provider_streams_reasoning_and_json_output():
    seen_request = None
    content_payload = {
        "thinking_summary_delta": {
            "stage": "planning",
            "action": "draft_plan",
            "summary": "Prepared an OpenAI Responses plan summary.",
            "observations": ["responses-streamed"],
            "next_step": "dispatch_worker",
            "confidence": 0.85,
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
                    'data: {"type":"response.reasoning_summary_text.delta","delta":"orchestrator considered the plan; "}',
                    'data: {"type":"response.reasoning_summary_text.done","text":"orchestrator considered the plan; then selected git status."}',
                    f'data: {json.dumps({"type": "response.output_text.delta", "delta": json.dumps(content_payload)})}',
                    "data: [DONE]",
                    "",
                ]
            ),
        )

    provider = OpenAIResponsesProvider(
        base_url="https://api.openai.test/v1",
        api_key="sk-secret-token",
        model="gpt-test",
        transport=httpx.MockTransport(handler),
    )

    result = await provider.complete_json("hello", schema_name="plan")

    assert result["answer"] == content_payload["answer"]
    assert result["thinking_summary_delta"]["summary"] == "Prepared an OpenAI Responses plan summary."
    assert result["model_message"] == {
        "has_reasoning_content": True,
        "reasoning_content_stored": True,
        "reasoning_source": "openai_responses_stream",
    }
    assert result["raw_reasoning_content"] == "orchestrator considered the plan; then selected git status."
    assert seen_request is not None
    assert str(seen_request.url) == "https://api.openai.test/v1/responses"
    assert seen_request.headers["authorization"] == "Bearer sk-secret-token"
    body = json.loads(seen_request.content)
    assert body["model"] == "gpt-test"
    assert body["input"] == "hello"
    assert body["stream"] is True
    assert body["reasoning"] == {"summary": "detailed"}


@pytest.mark.asyncio
async def test_openai_responses_provider_parses_non_streaming_output_text():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "output_text": json.dumps(
                    {
                        "thinking_summary_delta": {
                            "stage": "audit",
                            "action": "review",
                            "summary": "Auditor prepared a public summary.",
                            "observations": [],
                            "next_step": "finish",
                            "confidence": 0.8,
                        },
                        "answer": {"ok": True},
                    }
                ),
                "output": [
                    {
                        "type": "reasoning",
                        "summary": [
                            {
                                "type": "summary_text",
                                "text": "auditor checked public evidence.",
                            }
                        ],
                    }
                ],
            },
        )

    provider = OpenAIResponsesProvider(
        base_url="https://api.openai.test/v1",
        api_key="sk-test",
        model="gpt-test",
        transport=httpx.MockTransport(handler),
    )

    result = await provider.complete_json("hello", schema_name="audit_verdict")

    assert result["answer"] == {"ok": True}
    assert result["raw_reasoning_content"] == "auditor checked public evidence."
