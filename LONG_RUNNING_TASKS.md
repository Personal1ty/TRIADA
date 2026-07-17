# Long-Running Tasks

TRIADA models long-running work with heartbeat and checkpoint events. The MVP
contains a deterministic simulator for tests and CLI demos.

## Lease

A lease is the exclusive right for a worker to advance a task. In the current
MVP this is modeled at the service level rather than with a distributed lock.
Future multi-worker execution should persist lease owner, lease expiry, and
renewal evidence in the audit stream.

## Heartbeat

`HeartbeatService` emits `agent_heartbeat` payloads with:

- `trace_id`
- `agent_id`
- `current_stage`
- `last_completed_action`
- `elapsed_seconds`
- `created_at`

Heartbeats prove the worker is still active even when no artifact has been
created yet.

## Checkpoint

`LongTaskSimulator` emits checkpoint-style `thinking_summary_delta` events at a
configured interval. These summaries record public progress and references
without exposing raw chain-of-thought.

## Timeout

When virtual duration exceeds the timeout, the simulator emits `task_timeout`
and `task_cancelled`, then returns `timed_out`. Successful completion emits
`task_completed`.

## Fake Clock

Tests use `FakeClock` to advance virtual time deterministically. The fake clock
cannot move backwards, which keeps heartbeat and checkpoint ordering stable.

CLI demo:

```bash
python3 -m app.cli simulate-long-task
```
