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
        if not self.base_url:
            raise RuntimeError("LLM_BASE_URL is required for openai-compatible LLM calls")

        url = f"{self.base_url.rstrip('/')}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
        }

        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=30.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            raise RuntimeError(f"OpenAI-compatible LLM request failed: {self._redact(exc)}") from exc

        content = self._extract_content(data)
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"OpenAI-compatible LLM returned non-JSON content: {self._redact(exc)}"
            ) from exc

        if not isinstance(parsed, dict):
            raise RuntimeError("OpenAI-compatible LLM returned JSON that is not an object")
        return parsed

    def _extract_content(self, data: Any) -> str:
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("OpenAI-compatible LLM response missing assistant content") from exc

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

    def _redact(self, value: object) -> str:
        message = str(value)
        if self.api_key:
            message = message.replace(self.api_key, "[REDACTED]")
        return message
