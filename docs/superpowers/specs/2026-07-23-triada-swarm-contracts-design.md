# TRIADA Swarm Contracts Design

Date: 2026-07-23

## Goal

TRIADA must evolve from a fixed three-role pipeline into a configurable swarm
architecture where the system can create worker-auditor pairs, enforce audit
gates, scale pairs based on task weight, and present a human-ready result at the
end of each run.

The first implementation increment is contract-first: define machine-checkable
JSON contracts and route rules before building the local UI on top of them.

## Success Criteria

- The main swarm contract is expressible as JSON and validated by code.
- A valid swarm has exactly one orchestrator, at least three workers, one chief
  auditor, and one assigned auditor for every worker.
- Worker output cannot bypass its assigned auditor.
- Final human output cannot bypass the chief auditor.
- The orchestrator can classify task weight and use configurable scaling rules
  to choose how many worker-auditor pairs are active.
- Contract versions can be upgraded without silently weakening audit gates.
- The local UI can later render the same contracts, routes, reasoning records,
  summaries, and runtime events stored in PostgreSQL.

## Core Contract Shape

The top-level JSON contract is `swarm_contract@1.0`.

```json
{
  "schema_version": "1.0",
  "contract_version": "1.0",
  "topology": {
    "orchestrator": "orchestrator",
    "chief_auditor": "chief-auditor",
    "min_worker_auditor_pairs": 3
  },
  "worker_auditor_pairs": [
    {
      "worker_id": "worker-1",
      "auditor_id": "auditor-1",
      "capabilities": ["read_only_tools"],
      "max_parallel_steps": 1
    }
  ],
  "swarm_scaling": {
    "default_pairs": 3,
    "min_pairs": 3,
    "max_pairs": 12,
    "scale_by": ["task_weight", "step_count", "risk_policy", "tool_risk"]
  },
  "route_map": [],
  "invariants": [],
  "upgrade_policy": {},
  "human_output_contract": {
    "name": "human_review_packet",
    "version": "1.0"
  }
}
```

This contract is the source of truth for both runtime routing and UI graph
rendering. Runtime code should not infer hidden routes that are absent from the
contract.

## Role Topology

The minimum topology is:

```text
1 Orchestrator
3 Worker-Auditor pairs
1 Chief Auditor
1 Human Review Packet output
```

Each worker must have one assigned auditor. A worker may not submit a result
directly to the orchestrator, chief auditor, or human output. The assigned
auditor verifies worker evidence and either returns corrections to the worker or
submits an audit verdict to the chief auditor.

The chief auditor aggregates assigned-auditor verdicts and emits the final gate
verdict for the orchestrator. The orchestrator can then prepare a human-ready
packet only after this final gate passes or returns a structured explanation of
required corrections.

## Route Map

Routes are explicit, typed, and reasoned.

```json
[
  {
    "source": "human",
    "target": "orchestrator",
    "reason": "create_task",
    "input_contract": "task_request@1.0",
    "output_contract": "task_plan_request@1.0"
  },
  {
    "source": "orchestrator",
    "target": "worker",
    "reason": "assign_step",
    "input_contract": "worker_assignment@1.0",
    "output_contract": "worker_result@1.0"
  },
  {
    "source": "worker",
    "target": "assigned_auditor",
    "reason": "submit_evidence",
    "input_contract": "worker_result@1.0",
    "output_contract": "audit_verdict@1.0"
  },
  {
    "source": "assigned_auditor",
    "target": "worker",
    "reason": "request_correction",
    "input_contract": "audit_correction@1.0",
    "output_contract": "worker_result@1.0"
  },
  {
    "source": "assigned_auditor",
    "target": "chief_auditor",
    "reason": "escalate_verdict",
    "input_contract": "audit_verdict@1.0",
    "output_contract": "chief_audit_verdict@1.0"
  },
  {
    "source": "chief_auditor",
    "target": "orchestrator",
    "reason": "return_final_gate",
    "input_contract": "chief_audit_verdict@1.0",
    "output_contract": "human_review_packet@1.0"
  },
  {
    "source": "orchestrator",
    "target": "human",
    "reason": "deliver_human_packet",
    "input_contract": "human_review_packet@1.0",
    "output_contract": "human_decision@1.0"
  }
]
```

The route map is suitable for graph rendering. Each edge should expose source,
target, reason, input contract, output contract, status, and related audit
events.

## Task Weight And Scaling

The orchestrator assigns a task weight before creating worker-auditor pairs.

```json
{
  "task_weight_rules": [
    {
      "weight": "small",
      "conditions": {"max_steps": 1, "risk_policy": ["read_only"]},
      "worker_auditor_pairs": 3
    },
    {
      "weight": "medium",
      "conditions": {"max_steps": 5},
      "worker_auditor_pairs": 3
    },
    {
      "weight": "large",
      "conditions": {"min_steps": 6},
      "worker_auditor_pairs": 5
    },
    {
      "weight": "critical",
      "conditions": {"risk_policy": ["write", "destructive"]},
      "worker_auditor_pairs": 3,
      "requires_chief_auditor_strict_mode": true
    }
  ]
}
```

Scaling remains bounded by `swarm_scaling.min_pairs` and
`swarm_scaling.max_pairs`. Critical tasks do not automatically get more
parallelism; they get stricter gates and may reduce concurrency to preserve
review quality.

## Required Invariants

```json
[
  {
    "name": "worker_requires_assigned_auditor",
    "rule": "every worker_result must be routed to the worker's assigned auditor"
  },
  {
    "name": "no_worker_to_human_route",
    "rule": "workers cannot produce human_review_packet directly"
  },
  {
    "name": "no_orchestrator_final_without_chief_audit",
    "rule": "orchestrator cannot deliver human output without chief_audit_verdict"
  },
  {
    "name": "audit_gate_cannot_be_weakened_by_minor_upgrade",
    "rule": "minor contract upgrades cannot remove required auditor routes or verdict fields"
  }
]
```

These invariants must be validated when the contract is loaded and again before
runtime execution starts.

## Human Output Contract

The final output is for a human evaluator, not another internal agent.

`human_review_packet@1.0` should include:

- task summary
- final status
- chief auditor verdict
- worker results
- assigned auditor verdicts
- evidence references
- public thinking summaries
- sensitive raw reasoning references, not raw text by default
- unresolved risks
- recommended next decision

Raw reasoning content remains sensitive audit data. The UI may show it only in a
privileged local view and should label it separately from public summaries.

## Upgrade Policy

Contracts use semantic versions.

```json
{
  "upgrade_policy": {
    "allow_minor_upgrade": true,
    "breaking_changes_require": "new_major_version",
    "migration_required_for": [
      "route_removed",
      "required_field_removed",
      "audit_gate_weakened",
      "worker_auditor_pairing_changed"
    ],
    "forbidden_without_explicit_approval": [
      "remove_assigned_auditor",
      "allow_worker_to_human_route",
      "allow_orchestrator_final_without_chief_audit"
    ]
  }
}
```

The upgrade system allows TRIADA to evolve contracts while preventing silent
weakening of auditor checks.

## Local UI Scope

The UI is a second increment built on the contract and PostgreSQL data.

Required local screens:

- Swarm graph: active orchestrator, worker-auditor pairs, chief auditor, route
  reasons, route statuses, and contract names.
- Task trace: audit events from PostgreSQL in sequence order.
- Thinking view: public `thinking_summary_delta` records and privileged raw
  `model_reasoning_content_captured` records.
- Contract view: active JSON contracts and validation status.
- Swarm config view: min/max pairs, scaling rules, and task weight rules.

The UI should not create a separate truth model. It should read contract JSON
and persisted runtime events.

## Implementation Order

1. Add JSON/Pydantic swarm contract models and validators.
2. Add tests for minimum topology, worker-auditor pairing, route validity, audit
   gate invariants, and upgrade policy.
3. Add a default `swarm_contract@1.0` JSON file.
4. Wire ExecutionEngine to load the swarm contract without changing agent
   behavior yet.
5. Add route events so runtime traces contain graph edges and reasons.
6. Add chief auditor gate and human review packet.
7. Add local UI endpoints.
8. Add local UI graph and trace screens.

This order keeps the architecture testable before introducing UI complexity.
