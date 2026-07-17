# Event Schema

Audit events are stored as redacted payloads with trace-local sequence numbers
and hash-chain metadata.

## Generic Event Example

```json
{
  "id": "11111111-1111-1111-1111-111111111111",
  "event_type": "tool_executed",
  "trace_id": "22222222-2222-2222-2222-222222222222",
  "task_id": "33333333-3333-3333-3333-333333333333",
  "agent_id": "worker-1",
  "span_id": "44444444-4444-4444-4444-444444444444",
  "parent_span_id": null,
  "sequence": 3,
  "payload": {
    "tool": "shell",
    "command": ["python3", "-m", "pytest", "-q"],
    "risk_policy": "read_only",
    "exit_code": 0,
    "stdout_ref": ".triada/artifacts/pytest.out",
    "stderr_ref": ".triada/artifacts/pytest.err",
    "timed_out": false
  },
  "created_at": "2026-07-17T12:00:00",
  "previous_hash": "abc...",
  "event_hash": "def..."
}
```

## thinking_summary_delta Example

`thinking_summary_delta` is a public progress summary, not raw chain-of-thought.

```json
{
  "schema_version": "1.0",
  "event_id": "55555555-5555-5555-5555-555555555555",
  "trace_id": "22222222-2222-2222-2222-222222222222",
  "task_id": "33333333-3333-3333-3333-333333333333",
  "span_id": "44444444-4444-4444-4444-444444444444",
  "parent_span_id": null,
  "agent_id": "worker-1",
  "agent_role": "worker",
  "source": "runtime",
  "sequence": 1,
  "stage": "validation",
  "action": "run tests",
  "summary": "Validation is running against the requested test suite.",
  "observations": ["pytest started"],
  "input_refs": ["tests/triada/test_docs.py"],
  "output_refs": [],
  "next_step": "report results",
  "progress_percent": 80,
  "confidence": 0.8,
  "created_at": "2026-07-17T12:00:00Z",
  "metadata": {"command": "python3 -m pytest tests/triada/test_docs.py -q"}
}
```

## Common Event Types

- `task_created`
- `agent_heartbeat`
- `thinking_summary_delta`
- `tool_executed`
- `artifact_created`
- `task_completed`
- `task_timeout`
- `task_cancelled`
