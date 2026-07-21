from __future__ import annotations

import json
from typing import Any

import httpx

from app.llm.base import LLMProvider


class OpenAIResponsesProvider(LLMProvider):
    def __init__(
        self,
        *,
        base_url: str | None,
        api_key: str | None,
        model: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url or "https://api.openai.com/v1"
        self.api_key = api_key
        self.model = model
        self.transport = transport

    async def complete_json(self, prompt: str, *, schema_name: str) -> dict[str, Any]:
        message = await self.complete_message(prompt, schema_name=schema_name)
        try:
            parsed = json.loads(message["content"])
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"OpenAI Responses returned non-JSON content: {self._redact(exc)}") from None

        if not isinstance(parsed, dict):
            raise RuntimeError("OpenAI Responses returned JSON that is not an object")
        if message["has_reasoning_content"]:
            parsed["model_message"] = {
                "has_reasoning_content": True,
                "reasoning_content_stored": True,
                "reasoning_source": "openai_responses_stream",
            }
            parsed["raw_reasoning_content"] = message["raw_reasoning_content"]
        return parsed

    async def complete_message(self, prompt: str, *, schema_name: str) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("LLM_API_KEY is required for OpenAI Responses API calls")

        url = f"{self.base_url.rstrip('/')}/responses"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "input": prompt,
            "stream": True,
            "reasoning": {"summary": "detailed"},
        }

        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=60.0) as client:
                async with client.stream("POST", url, headers=headers, json=payload) as response:
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "")
                    if "text/event-stream" in content_type:
                        return await self._read_streaming_message(response)
                    body = (await response.aread()).decode("utf-8", errors="replace")
        except Exception as exc:
            raise RuntimeError(f"OpenAI Responses request failed: {self._redact(exc)}") from None

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return self._read_streaming_text(body)

        content = self._extract_output_text(data)
        reasoning = self._extract_reasoning_from_response(data)
        return {
            "content": content,
            "has_reasoning_content": bool(reasoning),
            "raw_reasoning_content": reasoning or None,
        }

    async def _read_streaming_message(self, response: httpx.Response) -> dict[str, Any]:
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        reasoning_done_text: str | None = None
        async for line in response.aiter_lines():
            payload = self._line_payload(line)
            if payload is None:
                continue
            if payload == "[DONE]":
                break
            try:
                data = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"OpenAI Responses returned invalid stream JSON: {self._redact(exc)}") from None
            content_part = self._extract_stream_content(data)
            if content_part:
                content_parts.append(content_part)
            reasoning_part = self._extract_stream_reasoning_delta(data)
            if reasoning_part:
                reasoning_parts.append(reasoning_part)
            reasoning_done = self._extract_stream_reasoning_done(data)
            if reasoning_done:
                reasoning_done_text = reasoning_done
        return self._final_stream_message(content_parts, reasoning_parts, reasoning_done_text)

    def _read_streaming_text(self, body: str) -> dict[str, Any]:
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        reasoning_done_text: str | None = None
        for line in body.splitlines():
            payload = self._line_payload(line)
            if payload is None:
                continue
            if payload == "[DONE]":
                break
            try:
                data = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"OpenAI Responses returned invalid stream JSON: {self._redact(exc)}") from None
            content_part = self._extract_stream_content(data)
            if content_part:
                content_parts.append(content_part)
            reasoning_part = self._extract_stream_reasoning_delta(data)
            if reasoning_part:
                reasoning_parts.append(reasoning_part)
            reasoning_done = self._extract_stream_reasoning_done(data)
            if reasoning_done:
                reasoning_done_text = reasoning_done
        return self._final_stream_message(content_parts, reasoning_parts, reasoning_done_text)

    def _final_stream_message(
        self,
        content_parts: list[str],
        reasoning_parts: list[str],
        reasoning_done_text: str | None,
    ) -> dict[str, Any]:
        content = "".join(content_parts)
        if not content:
            raise RuntimeError("OpenAI Responses missing output text")
        raw_reasoning_content = reasoning_done_text or "".join(reasoning_parts)
        return {
            "content": content,
            "has_reasoning_content": bool(raw_reasoning_content),
            "raw_reasoning_content": raw_reasoning_content or None,
        }

    def _line_payload(self, line: str) -> str | None:
        stripped = line.strip()
        if not stripped:
            return None
        if stripped.startswith("data:"):
            return stripped.removeprefix("data:").strip()
        return stripped

    def _extract_stream_content(self, data: Any) -> str:
        if not isinstance(data, dict):
            return ""
        if data.get("type") in {"response.output_text.delta", "response.output_text.done"}:
            value = data.get("delta") if "delta" in data else data.get("text")
            return value if isinstance(value, str) else ""
        return ""

    def _extract_stream_reasoning_delta(self, data: Any) -> str:
        if not isinstance(data, dict):
            return ""
        if data.get("type") in {"response.reasoning_summary_text.delta", "response.reasoning_text.delta"}:
            value = data.get("delta")
            return value if isinstance(value, str) else ""
        return ""

    def _extract_stream_reasoning_done(self, data: Any) -> str:
        if not isinstance(data, dict):
            return ""
        if data.get("type") in {"response.reasoning_summary_text.done", "response.reasoning_text.done"}:
            value = data.get("text")
            return value if isinstance(value, str) else ""
        return ""

    def _extract_output_text(self, data: Any) -> str:
        if not isinstance(data, dict):
            raise RuntimeError("OpenAI Responses response is not an object")
        output_text = data.get("output_text")
        if isinstance(output_text, str) and output_text:
            return output_text

        parts: list[str] = []
        output = data.get("output")
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                for part in content:
                    if isinstance(part, dict) and part.get("type") in {"output_text", "text"}:
                        text = part.get("text")
                        if isinstance(text, str):
                            parts.append(text)
        if parts:
            return "".join(parts)
        raise RuntimeError("OpenAI Responses missing output text")

    def _extract_reasoning_from_response(self, data: Any) -> str:
        if not isinstance(data, dict):
            return ""
        parts: list[str] = []
        output = data.get("output")
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, dict) or item.get("type") != "reasoning":
                    continue
                summary = item.get("summary")
                if isinstance(summary, list):
                    for part in summary:
                        if isinstance(part, dict) and isinstance(part.get("text"), str):
                            parts.append(part["text"])
                content = item.get("content")
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and isinstance(part.get("text"), str):
                            parts.append(part["text"])
                encrypted = item.get("encrypted_content")
                if isinstance(encrypted, str):
                    parts.append(encrypted)
        return "".join(parts)

    def _redact(self, value: object) -> str:
        text = str(value)
        if self.api_key:
            text = text.replace(self.api_key, "[REDACTED]")
        return text
