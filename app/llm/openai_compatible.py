import asyncio
import json
import re
import time
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
        initial_raw_reasoning = message.get("raw_reasoning_content")
        try:
            parsed = self._parse_message_json(message)
        except json.JSONDecodeError as exc:
            message = await self.complete_message(
                self._repair_prompt(
                    original_prompt=prompt,
                    bad_content=str(message.get("content", "")),
                    schema_name=schema_name,
                    error=str(exc),
                ),
                schema_name=schema_name,
            )
            try:
                parsed = self._parse_message_json(message)
            except json.JSONDecodeError as repair_exc:
                raise RuntimeError(
                    f"OpenAI-compatible LLM returned non-JSON content: {self._redact(repair_exc)}"
                ) from None

        if not isinstance(parsed, dict):
            raise RuntimeError("OpenAI-compatible LLM returned JSON that is not an object")
        if initial_raw_reasoning and not message.get("raw_reasoning_content"):
            message["raw_reasoning_content"] = initial_raw_reasoning
            message["has_reasoning_content"] = True
        if message["has_reasoning_content"]:
            parsed["model_message"] = {
                "has_reasoning_content": True,
                "reasoning_content_stored": True,
            }
            parsed["raw_reasoning_content"] = message["raw_reasoning_content"]
        return parsed

    def _parse_message_json(self, message: dict[str, Any]) -> Any:
        return self._parse_json_object(str(message.get("content", "")))

    def _repair_prompt(self, *, original_prompt: str, bad_content: str, schema_name: str, error: str) -> str:
        return "\n".join(
            [
                "Repair the following TRIADA model output into one valid JSON object.",
                f"Schema name: {schema_name}",
                f"JSON parse error: {error}",
                "Return only JSON. Do not include markdown or prose.",
                "The JSON object must preserve TRIADA fields such as thinking_summary_delta and answer when present.",
                "Original user prompt:",
                original_prompt,
                "Bad model output:",
                bad_content,
            ]
        )

    def _parse_json_object(self, content: str) -> Any:
        try:
            return json.loads(content)
        except json.JSONDecodeError as first_error:
            for extracted in self._json_object_candidates(content):
                try:
                    parsed = json.loads(extracted)
                except json.JSONDecodeError:
                    continue
                if self._looks_like_triada_response(parsed):
                    return parsed
            for extracted in self._json_object_candidates(content):
                try:
                    return json.loads(extracted)
                except json.JSONDecodeError:
                    continue
            raise first_error

    def _json_object_candidates(self, content: str) -> list[str]:
        candidates = [
            match.group(1).strip()
            for match in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
        ]
        candidates.extend(self._extract_balanced_json_objects(content))
        return candidates

    def _extract_balanced_json_objects(self, content: str) -> list[str]:
        candidates: list[str] = []
        start = content.find("{")
        while start != -1:
            depth = 0
            in_string = False
            escaped = False
            for index in range(start, len(content)):
                char = content[index]
                if in_string:
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == '"':
                        in_string = False
                    continue
                if char == '"':
                    in_string = True
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        candidates.append(content[start : index + 1])
                        break
            start = content.find("{", start + 1)
        return candidates

    def _looks_like_triada_response(self, value: Any) -> bool:
        return isinstance(value, dict) and (
            "answer" in value
            or "thinking_summary_delta" in value
            or "model_message" in value
            or "raw_reasoning_content" in value
        )

    async def complete_message(self, prompt: str, *, schema_name: str) -> dict[str, Any]:
        if not self.base_url:
            raise RuntimeError("LLM_BASE_URL is required for openai-compatible LLM calls")

        url = f"{self.base_url.rstrip('/')}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a TRIADA agent endpoint. Return only one valid JSON object. "
                        "Do not wrap it in markdown. Do not include prose outside JSON."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "stream": True,
            "response_format": {"type": "json_object"},
        }
        if self._is_deepseek_thinking_endpoint():
            payload["thinking"] = {"type": "enabled"}
            payload["reasoning_effort"] = "high"

        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=30.0) as client:
                async with client.stream("POST", url, headers=headers, json=payload) as response:
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "")
                    if "text/event-stream" in content_type:
                        return await self._read_streaming_message(
                            response,
                            max_duration_seconds=30.0,
                        )
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
            "raw_reasoning_content": self._extract_reasoning_content(data),
        }

    def _read_streaming_text(self, body: str) -> dict[str, Any]:
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
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
            reasoning = self._extract_reasoning_content(data)
            if reasoning:
                reasoning_parts.append(reasoning)
            part = self._extract_stream_content(data)
            if part:
                content_parts.append(part)
        content = "".join(content_parts)
        if not content:
            raise RuntimeError("OpenAI-compatible LLM response missing assistant content")
        raw_reasoning_content = "".join(reasoning_parts)
        return {
            "content": content,
            "has_reasoning_content": bool(raw_reasoning_content),
            "raw_reasoning_content": raw_reasoning_content or None,
        }

    async def _read_streaming_message(
        self,
        response: httpx.Response,
        *,
        max_duration_seconds: float = 30.0,
    ) -> dict[str, Any]:
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        deadline = time.monotonic() + max_duration_seconds
        lines = response.aiter_lines().__aiter__()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("OpenAI-compatible LLM stream exceeded maximum duration")
            try:
                line = await asyncio.wait_for(lines.__anext__(), timeout=remaining)
            except StopAsyncIteration:
                break
            except TimeoutError:
                raise RuntimeError(
                    "OpenAI-compatible LLM stream exceeded maximum duration"
                ) from None
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
            reasoning = self._extract_reasoning_content(data)
            if reasoning:
                reasoning_parts.append(reasoning)
            part = self._extract_stream_content(data)
            if part:
                content_parts.append(part)
        content = "".join(content_parts)
        if not content:
            raise RuntimeError("OpenAI-compatible LLM response missing assistant content")
        raw_reasoning_content = "".join(reasoning_parts)
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
        return bool(self._extract_reasoning_content(data))

    def _extract_reasoning_content(self, data: Any) -> str:
        choices = data.get("choices") if isinstance(data, dict) else None
        if not isinstance(choices, list):
            return ""
        parts: list[str] = []
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            for key in ("delta", "message"):
                value = choice.get(key)
                if isinstance(value, dict) and value.get("reasoning_content"):
                    parts.append(str(value["reasoning_content"]))
        return "".join(parts)

    def _is_deepseek_thinking_endpoint(self) -> bool:
        base_url = (self.base_url or "").lower()
        model = self.model.lower()
        return "api.deepseek.com" in base_url or model.startswith("deepseek-")

    def _redact(self, value: object) -> str:
        message = str(value)
        if self.api_key:
            message = message.replace(self.api_key, "[REDACTED]")
        return message
