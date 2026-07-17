from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.audit.redaction import contains_secret, redact_text
from app.events.models import ThinkingSummaryDelta


def make_delta(**overrides):
    base = {
        "schema_version": "1.0",
        "event_id": uuid4(),
        "trace_id": uuid4(),
        "task_id": uuid4(),
        "span_id": uuid4(),
        "parent_span_id": None,
        "agent_id": "worker-1",
        "agent_role": "worker",
        "source": "runtime",
        "sequence": 1,
        "stage": "validation",
        "action": "check",
        "summary": "Checking runtime result.",
        "observations": ["Command completed with exit code 0."],
        "input_refs": ["event:1"],
        "output_refs": [],
        "next_step": "Audit result",
        "progress_percent": 50,
        "confidence": 0.8,
        "created_at": datetime.now(UTC),
        "metadata": {},
    }
    base.update(overrides)
    return ThinkingSummaryDelta(**base)


def test_thinking_summary_delta_rejects_extra_fields():
    with pytest.raises(ValidationError):
        make_delta(extra_field="not allowed")


def test_thinking_summary_delta_rejects_hidden_reasoning_phrase():
    with pytest.raises(ValidationError):
        make_delta(summary="Let me think step by step about hidden reasoning.")


def test_thinking_summary_delta_rejects_secret_text():
    with pytest.raises(ValidationError):
        make_delta(summary="Authorization: Bearer sk-secret")


def test_redact_text_masks_common_secret_patterns():
    text = "password=my-pass Authorization: Bearer sk-token"
    redacted = redact_text(text)
    assert "my-pass" not in redacted
    assert "sk-token" not in redacted
    assert "[REDACTED]" in redacted


def test_contains_secret_detects_private_key_marker():
    assert contains_secret("-----BEGIN PRIVATE KEY-----\nabc")
