# TRIADA Role Contracts

TRIADA role contracts define the stable handoff surface between Orchestrator,
Worker, and Auditor. They are intentionally small and machine-checkable so the
system can scale by adding more workers, tools, or routes without weakening role
boundaries.

## Roles

- Orchestrator owns planning, routing, and risk classification.
- Worker owns execution, tool use, and evidence collection.
- Auditor owns verification, quality gates, and correction routing.

## Routes

```text
orchestrator --assign_step--> worker
worker       --submit_result--> auditor
auditor      --return_verdict--> orchestrator
```

Each route declares its input contract, output contract, and required audit
events. Routes are source/purpose unique, and every route endpoint must reference
a declared role.

## Handoff

Every handoff carries:

- `trace_id` and `task_id`
- `source`, `target`, and `purpose`
- `input_contract` and `output_contract`
- `input_refs` and `output_refs`
- `allowed_tools`
- `risk_policy`
- `acceptance_criteria`

The handoff contract rejects self-routing. This keeps role boundaries explicit
and makes routes predictable in tests and audit trails.

## Scale Rules

- Orchestrator scales by task.
- Worker scales by step.
- Auditor scales by trace.

This lets TRIADA add worker pools or specialized auditors without changing the
core handoff shape.
