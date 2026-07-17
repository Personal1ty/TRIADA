# Security Model

TRIADA treats delegated automation as evidence-driven work with explicit risk
controls. This document describes the MVP policy implemented by the current
codebase.

## Redaction

Audit payloads and tool output pass through redaction before storage or public
projection. Current patterns redact password-like fields, API keys, bearer/basic
authorization values, private keys, OpenAI-style `sk-...` tokens, and sensitive
dictionary keys such as `token`, `authorization`, and `client_secret`.

Tool output is also truncated through `max_tool_output_bytes` to limit accidental
data exposure.

## Approval And Risk Policy

Tool requests carry a `risk_policy`:

- `read_only`: allowed without additional metadata.
- `low_risk_write`: requires `expected_change` and `validation_command`.
- `high_risk_write`: requires an `approval_ref`.
- `destructive`: requires an `approval_ref`.

Adapters must call `ensure_risk_allowed` before executing work and should expose
dry-run behavior when the underlying tool can support it.

## Reasoning Policy

TRIADA must not capture or expose raw chain-of-thought. Public progress is
represented by bounded `thinking_summary_delta` records containing stage, action,
summary, observations, refs, confidence, and metadata. The schema rejects unsafe
phrases that request hidden reasoning or raw chain-of-thought and rejects secret
text in public summaries.

## Operational Notes

- Keep `.env` out of source control.
- Prefer the fake provider in tests and local demos.
- Do not place tokens in task goals, metadata, tool commands, or artifacts.
- Treat audit logs as sensitive operational records even when redacted.
