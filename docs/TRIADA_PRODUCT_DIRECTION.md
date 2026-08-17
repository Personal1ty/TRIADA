# TRIADA Product Direction

TRIADA is evolving from a DevOps task runner into a domain-agnostic runtime for
observable, auditable swarms. DevOps adapters remain useful as one execution
domain, but they are not the product boundary.

## Product promise

Given a complex goal, TRIADA should make it possible to see:

- how the goal was decomposed;
- which agents are active and why;
- how work is routed between roles;
- what evidence supports each result;
- where quality, cost, latency, or uncertainty changed;
- when human intervention is required.

## Delivery sequence

### P0 — Controlled swarm runtime

- bounded scheduler with global and per-worker limits;
- explicit task and agent state transitions;
- task weight and scaling rules enforced at runtime;
- Run Observatory UI with task list, graph, timeline, and inspector.

### P1 — Quality and replay

- contract compatibility checks;
- evidence-linked audit verdicts;
- contract diffs and version comparison;
- replay and correction paths;
- quality, cost, and latency metrics.

### P2 — Memory and research

- task and decision memory;
- context budgeting and checkpoints;
- semantic retrieval over prior research;
- conflict detection between findings and parameters.

The first memory increment stores validated decision, observation, constraint,
and summary notes as append-only audit events. Retrieval currently uses a
deterministic token-overlap ranking; a pgvector backend can replace the ranking
implementation without changing the memory API.

### P3 — Nested swarms

- macro- and micro-triads;
- nested contracts and lifecycle boundaries;
- error-radius and propagation policies;
- specialized research or analysis subgraphs.

### P4 — Controlled self-improvement

- proposed contract changes;
- auditor review of changes;
- human approval for structural mutations;
- reproducible versioned execution.

## Runtime boundary

TRIADA owns task identity, contracts, audit events, redaction, human gates, and
operator-facing state. An external graph runtime such as LangGraph may be used
inside a bounded adapter for long-running or nested workflows, but it must not
become a second source of truth for TRIADA tasks and audit history.

The first adapter spike is intentionally dependency-free. It maps a TRIADA
checkpoint to a LangGraph-compatible `{thread_id, checkpoint_id}` config; an
actual LangGraph runtime can be plugged in later behind this boundary.

The first actual spike now lives in `app/runtime/langgraph_spike.py`: a small
checkpointed research graph with `research -> audit` nodes. It is evaluated
separately from TRIADA execution and does not own task identity or audit history.
