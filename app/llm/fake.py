import hashlib
from typing import Any

from app.llm.base import LLMProvider


class FakeLLMProvider(LLMProvider):
    async def complete_json(self, prompt: str, *, schema_name: str) -> dict[str, Any]:
        digest = hashlib.sha256(f"{schema_name}:{prompt}".encode("utf-8")).hexdigest()[:12]
        summaries: dict[str, dict[str, Any]] = {
            "plan": {
                "stage": "planning",
                "action": "draft_plan",
                "summary": f"Prepared deterministic fake plan {digest}.",
                "observations": ["No private chain-of-thought is exposed."],
                "next_step": "dispatch_worker",
                "confidence": 1.0,
            },
            "worker_result": {
                "stage": "execution",
                "action": "complete_worker_task",
                "summary": f"Prepared deterministic fake worker result {digest}.",
                "observations": ["Output is derived from the prompt and schema only."],
                "next_step": "audit_result",
                "confidence": 1.0,
            },
            "audit_verdict": {
                "stage": "audit",
                "action": "evaluate_result",
                "summary": f"Prepared deterministic fake audit verdict {digest}.",
                "observations": ["Fake audit verdict is public-safe."],
                "next_step": "return_verdict",
                "confidence": 1.0,
            },
        }
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
            "thinking_summary_delta": summaries.get(
                schema_name,
                {
                    "stage": "response",
                    "action": "complete_json",
                    "summary": f"Prepared deterministic fake response {digest}.",
                    "observations": ["Unknown schema used default fake response shape."],
                    "next_step": "return_response",
                    "confidence": 1.0,
                },
            ),
            "answer": answers.get(
                schema_name,
                {"response_id": f"fake-response-{digest}", "content": prompt},
            ),
        }
