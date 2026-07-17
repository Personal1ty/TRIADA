from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.audit.redaction import contains_secret, redact_payload, redact_text
from app.events.models import AuditVerdict, AuditViolation, ThinkingSummaryDelta, ToolExecutionRecord


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


def test_redact_payload_masks_values_for_sensitive_keys():
    payload = {
        "password": "plain-secret",
        "Authorization": "Bearer abcdef123456",
        "nested": {"refresh_token": "rt-123456"},
    }

    redacted = redact_payload(payload)

    assert redacted["password"] == "[REDACTED]"
    assert redacted["Authorization"] == "[REDACTED]"
    assert redacted["nested"]["refresh_token"] == "[REDACTED]"


def test_redact_payload_does_not_mask_tokenization_key():
    payload = {"tokenization": "ordinary text"}

    assert redact_payload(payload) == payload


def test_tool_execution_record_exposes_tool_field():
    record = ToolExecutionRecord(
        tool="shell",
        command=["false"],
        started_at=None,
        finished_at=None,
        exit_code=1,
        stdout_ref=None,
        stderr_ref=None,
        timed_out=False,
    )

    assert record.tool == "shell"


def test_tool_execution_record_accepts_tool_name_alias():
    record = ToolExecutionRecord(tool_name="shell")

    assert record.tool == "shell"


def test_audit_violation_exposes_rule_id_and_evidence_event_ids():
    violation = AuditViolation(
        rule_id="TOOL_FAILURE_NOT_REPORTED",
        message="Tool failure was not reported.",
        evidence_event_ids=["event-1"],
    )

    assert violation.rule_id == "TOOL_FAILURE_NOT_REPORTED"
    assert violation.evidence_event_ids == ["event-1"]


def test_audit_violation_accepts_legacy_aliases():
    violation = AuditViolation(
        code="TOOL_FAILURE_NOT_REPORTED",
        message="Tool failure was not reported.",
        evidence_refs=["event-1"],
    )

    assert violation.rule_id == "TOOL_FAILURE_NOT_REPORTED"
    assert violation.evidence_event_ids == ["event-1"]


def test_audit_verdict_exposes_evidence_event_ids():
    verdict = AuditVerdict(verdict="fail", evidence_event_ids=["event-1"])

    assert verdict.evidence_event_ids == ["event-1"]
