import json
from typing import Any

import httpx

from app.llm.base import LLMProvider


class OpenAICompatibleProvider(LLMProvider):
    def __init__(
        self,
        *,
        base_url: str | None,
        api_key: str | None,
        model: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.transport = transport

    async def complete_json(self, prompt: str, *, schema_name: str) -> dict[str, Any]:
        message = await self.complete_message(prompt, schema_name=schema_name)
        try:
            parsed = json.loads(message["content"])
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"OpenAI-compatible LLM returned non-JSON content: {self._redact(exc)}"
            ) from None

        if not isinstance(parsed, dict):
            raise RuntimeError("OpenAI-compatible LLM returned JSON that is not an object")
        if message["has_reasoning_content"]:
            parsed["model_message"] = {
                "has_reasoning_content": True,
                "reasoning_content_redacted": True,
            }
        return parsed

    async def complete_message(self, prompt: str, *, schema_name: str) -> dict[str, Any]:
        if not self.base_url:
            raise RuntimeError("LLM_BASE_URL is required for openai-compatible LLM calls")

        url = f"{self.base_url.rstrip('/')}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
        }

        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=30.0) as client:
                async with client.stream("POST", url, headers=headers, json=payload) as response:
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "")
                    if "text/event-stream" in content_type:
                        return await self._read_streaming_message(response)
                    body = (await response.aread()).decode("utf-8", errors="replace")
                    try:
                        data = json.loads(body)
                    except json.JSONDecodeError:
                        return self._read_streaming_text(body)
        except Exception as exc:
            raise RuntimeError(
                f"OpenAI-compatible LLM request failed: {self._redact(exc)}"
            ) from None

        content = self._extract_content(data)
        return {
            "content": content,
            "has_reasoning_content": self._has_reasoning_content(data),
        }

    def _read_streaming_text(self, body: str) -> dict[str, Any]:
        content_parts: list[str] = []
        has_reasoning_content = False
        for line in body.splitlines():
            payload = self._line_payload(line)
            if payload is None:
                continue
            if payload == "[DONE]":
                break
            try:
                data = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"OpenAI-compatible LLM returned invalid stream JSON: {self._redact(exc)}"
                ) from None
            has_reasoning_content = has_reasoning_content or self._has_reasoning_content(data)
            part = self._extract_stream_content(data)
            if part:
                content_parts.append(part)
        content = "".join(content_parts)
        if not content:
            raise RuntimeError("OpenAI-compatible LLM response missing assistant content")
        return {"content": content, "has_reasoning_content": has_reasoning_content}

    async def _read_streaming_message(self, response: httpx.Response) -> dict[str, Any]:
        content_parts: list[str] = []
        has_reasoning_content = False
        async for line in response.aiter_lines():
            payload = self._line_payload(line)
            if payload is None:
                continue
            if payload == "[DONE]":
                break
            try:
                data = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"OpenAI-compatible LLM returned invalid stream JSON: {self._redact(exc)}"
                ) from None
            has_reasoning_content = has_reasoning_content or self._has_reasoning_content(data)
            part = self._extract_stream_content(data)
            if part:
                content_parts.append(part)
        content = "".join(content_parts)
        if not content:
            raise RuntimeError("OpenAI-compatible LLM response missing assistant content")
        return {"content": content, "has_reasoning_content": has_reasoning_content}

    def _line_payload(self, line: str) -> str | None:
        stripped = line.strip()
        if not stripped:
            return None
        if stripped.startswith("data:"):
            return stripped.removeprefix("data:").strip()
        return stripped

    def _extract_stream_content(self, data: Any) -> str:
        choices = data.get("choices") if isinstance(data, dict) else None
        if not isinstance(choices, list):
            return ""
        parts: list[str] = []
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta")
            if isinstance(delta, dict):
                content = delta.get("content")
                if isinstance(content, str):
                    parts.append(content)
            message = choice.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str):
                    parts.append(content)
        return "".join(parts)

    def _extract_content(self, data: Any) -> str:
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise RuntimeError("OpenAI-compatible LLM response missing assistant content") from None

        if isinstance(content, str):
            return content

        if isinstance(content, list):
            text_parts = [
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") in {None, "text"}
            ]
            if text_parts:
                return "".join(text_parts)

        raise RuntimeError("OpenAI-compatible LLM response content is not text")

    def _has_reasoning_content(self, data: Any) -> bool:
        choices = data.get("choices") if isinstance(data, dict) else None
        if not isinstance(choices, list):
            return False
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            for key in ("delta", "message"):
                value = choice.get(key)
                if isinstance(value, dict) and value.get("reasoning_content"):
                    return True
        return False

    def _redact(self, value: object) -> str:
        message = str(value)
        if self.api_key:
            message = message.replace(self.api_key, "[REDACTED]")
        return message
