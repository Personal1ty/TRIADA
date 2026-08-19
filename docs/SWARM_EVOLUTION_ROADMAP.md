# TRIADA Swarm Evolution Roadmap

## Goal

Evolve TRIADA from an observable swarm executor into a domain-agnostic operating
system for designing, balancing, researching, and supervising swarms.

The source of truth remains TRIADA's append-only audit trail and PostgreSQL
state. Obsidian is a human-facing knowledge projection; LangGraph is an
optional nested runtime, not a replacement for TRIADA lifecycle ownership.

## Current baseline

- Orchestrator, Worker, Auditor roles with explicit contracts.
- Lifecycle validation, bounded scheduling, scaling, approvals, replay,
  checkpoints, quality metrics, and Run Observatory UI.
- Structured append-only memory with lexical retrieval and optional pgvector.
- Live pgvector smoke verified on local PostgreSQL/pgvector.
- Optional isolated LangGraph research spike.

## Delivery sequence

### Phase 1 — Method and resource economics

Scope: items 38, 48, 49, 50, 52.

- `ResourceBudget` for tokens, wall-clock time, parallel branches, and retries.
- `PriorityPolicy` and auditable allocation decisions.
- Budget-aware scheduler admission and stop reasons.
- Contract v2 fields and metrics for utilization, waste, and sufficiency.

Gate: a run explains why a branch was started, limited, escalated, or stopped.

### Phase 2 — Swarm memory graph

Scope: items 39, 40, 42.

- First-class entities for observations, hypotheses, parameters, decisions,
  evidence, and conflicts.
- Relations: `supports`, `contradicts`, `derived_from`, `supersedes`,
  `depends_on`, and `validated_by`.
- Reindex/rebuild from audit events.
- Conflict and stale-knowledge projections in the API and UI.

Gate: every decision can show its evidence, predecessors, successors, and
conflicting parameters.

### Phase 3 — Deep R&D runtime

Scope: item 41 and the research part of item 55.

- Research-question contract and parameter catalog.
- Hypothesis generation, evidence collection, “why/how” expansion, and
  unresolved-question tracking.
- LangGraph subgraphs only behind TRIADA checkpoints, budgets, and audit events.

Implemented slice: append-only evidence records can be linked to hypotheses and
parameters, with deterministic confidence and coverage projection in the API
and Observatory UI. The optional LangGraph subgraph expands and audits the
bounded plan while leaving persistence and tool authority with TRIADA.
Parameter influence records now add explicit weighted edges (`-1..1`) between
catalog parameters, making side effects and strong relationships visible.
Resource usage records now aggregate tokens, duration, estimated cost, and
branches by role, giving the operator a first tokenomics/throughput view.
Playbook v1 now records versioned runs with quality and resource outcomes so
future playbooks can be compared and improved from measured executions.
Playbook templates now define reusable stages, capability scope, and acceptance
criteria as append-only versioned contracts.
Replay requests now retain source-run lineage, and failure patterns are
deduplicated into a reusable catalog with symptom, cause, and mitigation.
Capability registry and Worker-side enforcement now make ownership, risk,
approval, and audit requirements visible and testable.
Memory notes now support expiry timestamps, with stale-knowledge counts in the
graph projection and Observatory.

Gate: a research run produces a reproducible evidence map and explicit
uncertainty instead of only a final narrative.

### Phase 4 — Visual swarm language

Scope: items 43–45.

- Operator view for state, approvals, budgets, errors, and throughput.
- Architect view for contracts, clusters, policies, and topology.
- Research view for hypotheses, evidence, conflicts, and parameter influence.
- Obsidian projections and stable 2D graph semantics before any VR work.

Gate: an operator can identify the active bottleneck and an architect can trace
one decision through agents, parameters, evidence, and resource allocation.

### Phase 5 — Capability and sub-agent boundaries

Scope: items 46–47.

- Capability registry for MCP/tools and risk policies.
- Sub-agent scopes, allowed instructions, output schemas, and budgets.
- Redis-backed leases/queues only where Postgres durability is insufficient.

Gate: every tool or sub-agent action has an owner, scope, budget, approval rule,
and audit record.

### Phase 6 — Playbooks, roles, and external applications

Scope: items 51, 53–55.

- Personal rules, reusable playbooks, failure catalog, and decision heuristics.
- Domain adapters for research, analysis, design, and tool-backed workflows.
- Cost/throughput benchmarks and service packaging hypotheses.
- AGI/future scenarios kept as explicit research domains, not runtime policy.

Gate: a playbook is derived from measured runs and can be replayed, compared,
and improved without hidden assumptions.

## Critical path

`ResourceBudget` → memory relations → R&D runtime → visual projections →
capability boundaries → playbooks and economics.

## Non-goals for now

- Repositioning TRIADA as a DevOps-only system.
- Replacing TRIADA state with LangGraph state.
- Making Obsidian the production database.
- Building VR before 2D graph semantics are useful.
- Creating a global template engine before real playbooks and metrics exist.

## Working cadence

Each increment follows: failing test → minimal implementation → focused tests →
full suite → documentation → Git commit/push → Obsidian update.
