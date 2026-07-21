from __future__ import annotations

import hashlib
from typing import Any

from app.llm.base import LLMProvider


class CodexBridgeProvider(LLMProvider):
    """Deterministic bridge for Codex-operated demos.

    This provider does not expose Codex hidden reasoning. It records explicit
    Codex-authored reasoning notes so the TRIADA audit pipeline can be shown
    without an external LLM API key.
    """

    async def complete_json(self, prompt: str, *, schema_name: str) -> dict[str, Any]:
        digest = hashlib.sha256(f"codex-bridge:{schema_name}:{prompt}".encode("utf-8")).hexdigest()[:12]
        return {
            "thinking_summary_delta": self._summary(schema_name, digest),
            "answer": self._answer(schema_name, prompt, digest),
            "model_message": {
                "has_reasoning_content": True,
                "reasoning_content_stored": True,
                "reasoning_source": "codex_bridge",
            },
            "raw_reasoning_content": self._reasoning_note(schema_name, prompt, digest),
        }

    def _summary(self, schema_name: str, digest: str) -> dict[str, Any]:
        summaries: dict[str, dict[str, Any]] = {
            "plan": {
                "stage": "planning",
                "action": "codex_bridge_plan",
                "summary": "Codex bridge prepared an orchestrator plan for a safe git status check.",
                "observations": ["The requested task fits the read-only git tool."],
                "next_step": "dispatch_worker",
                "confidence": 1.0,
            },
            "worker_result": {
                "stage": "execution",
                "action": "codex_bridge_worker_review",
                "summary": "Codex bridge prepared the worker to execute the approved git status step.",
                "observations": ["The worker will use the minimal git status tool."],
                "next_step": "run_tool",
                "confidence": 1.0,
            },
            "audit_verdict": {
                "stage": "audit",
                "action": "codex_bridge_audit",
                "summary": "Codex bridge reviewed the worker evidence for the demo trace.",
                "observations": ["Tool evidence is present in the audit stream."],
                "next_step": "return_verdict",
                "confidence": 1.0,
            },
        }
        return summaries.get(
            schema_name,
            {
                "stage": "response",
                "action": "codex_bridge_response",
                "summary": f"Codex bridge prepared response {digest}.",
                "observations": ["Unknown schema used a default response."],
                "next_step": "return_response",
                "confidence": 1.0,
            },
        )

    def _answer(self, schema_name: str, prompt: str, digest: str) -> dict[str, Any]:
        if schema_name == "plan":
            return {
                "plan_id": f"codex-plan-{digest}",
                "steps": [
                    {
                        "id": "step-1",
                        "title": "Inspect git status",
                        "description": "Run git status and summarize repository state.",
                        "allowed_tools": ["git"],
                    }
                ],
            }
        if schema_name == "worker_result":
            return {
                "result_id": f"codex-worker-{digest}",
                "status": "ready",
                "output": "Worker prepared to run git status.",
            }
        if schema_name == "audit_verdict":
            return {
                "verdict_id": f"codex-audit-{digest}",
                "approved": True,
                "issues": [],
            }
        return {"response_id": f"codex-response-{digest}", "content": prompt}

    def _reasoning_note(self, schema_name: str, prompt: str, digest: str) -> str:
        return (
            f"Codex bridge explicit reasoning note {digest}: schema={schema_name}; "
            "this is an audit-visible reasoning record authored for the TRIADA demo, "
            "not hidden Codex chain-of-thought. "
            f"Prompt snapshot: {prompt[:240]}"
        )
