# Audit Model

TRIADA audit data is an append-only event stream keyed by `trace_id`.

## Append-Only Events

Each event includes:

- `id`
- `event_type`
- `trace_id`
- `task_id`
- `agent_id`
- `span_id` and `parent_span_id`
- `sequence`
- `payload`
- `created_at`
- `previous_hash`
- `event_hash`

Events are ordered by sequence inside a trace. The repository rejects duplicate
event ids and duplicate trace sequence values.

## Hash Chain

`AuditEventRepository` computes `event_hash` from canonical JSON for the event
plus the previous event hash. `verify_trace` checks sequence continuity,
duplicate ids, previous-hash links, and hash recomputation.

The first event in a trace uses an empty previous hash. Any mutation of a stored
event payload, timestamp, id, sequence, or link invalidates the trace.

## Auditor Evidence Priority

The Auditor should prefer evidence in this order:

1. Tool execution records and exit codes.
2. Validation result records and artifact checksums.
3. Required artifact names and paths.
4. Public thinking summary deltas.
5. Worker prose summaries.

When a worker summary claims success but the evidence is missing or contradicts
tool results, the Auditor returns `corrections_required`.
