import hashlib
from typing import Any

from app.llm.base import LLMProvider


class FakeLLMProvider(LLMProvider):
    async def complete_json(self, prompt: str, *, schema_name: str) -> dict[str, Any]:
        digest = hashlib.sha256(f"{schema_name}:{prompt}".encode("utf-8")).hexdigest()[:12]
        answers: dict[str, dict[str, Any]] = {
            "plan": {
                "plan_id": f"fake-plan-{digest}",
                "steps": [{"id": "step-1", "description": prompt}],
            },
            "worker_result": {
                "result_id": f"fake-worker-{digest}",
                "status": "completed",
                "output": prompt,
            },
            "audit_verdict": {
                "verdict_id": f"fake-audit-{digest}",
                "approved": True,
                "issues": [],
            },
        }
        return {
            "thinking_summary_delta": f"Fake {schema_name} response {digest}",
            "answer": answers.get(
                schema_name,
                {"response_id": f"fake-response-{digest}", "content": prompt},
            ),
        }
