# TRIADA Role Contracts

TRIADA contracts define the stable handoff surface between Orchestrator,
Workers, assigned Auditors, Chief Auditor, and the final human review packet.
They are intentionally small and machine-checkable so the system can scale by
adding worker-auditor pairs, tools, or routes without weakening role boundaries.

## Roles

- Orchestrator owns planning, routing, and risk classification.
- Worker owns execution, tool use, and evidence collection.
- Assigned Auditor owns verification for one worker-auditor pair.
- Chief Auditor owns the final gate before a human review packet is delivered.

## Routes

```text
human            --create_task-----------> orchestrator
orchestrator     --assign_step-----------> worker
worker           --submit_evidence-------> assigned_auditor
assigned_auditor --request_correction----> worker
assigned_auditor --escalate_verdict------> chief_auditor
chief_auditor    --return_final_gate-----> orchestrator
orchestrator     --deliver_human_packet--> human
```

Each route declares its input contract, output contract, and required audit
events. Routes are source/purpose unique, and every route endpoint must reference
a declared role.

The default swarm contract is stored in
`app/contracts/default_swarm_contract.json` and exposed through
`GET /v1/swarm/contract`.

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

## Swarm Rules

- A valid swarm has exactly one orchestrator.
- A valid swarm has at least three worker-auditor pairs.
- Every worker has one assigned auditor.
- Worker results can only move to the assigned auditor.
- The orchestrator cannot deliver a human packet until the chief auditor emits
  `chief_audit_verdict`.
- Runtime route selections are persisted as `swarm_route_selected` events and
  are exposed through `GET /v1/tasks/{task_id}/swarm-graph`.

## Scale Rules

- Orchestrator scales by task.
- Worker-auditor pairs scale by task weight, step count, risk policy, and tool
  risk.
- Chief Auditor scales by trace.

This lets TRIADA add worker pools or specialized auditors without changing the
core handoff shape.

## Local UI

`GET /ui` serves a local dashboard that shows the default contract, graph-ready
route events, and public thinking summaries. It does not render raw reasoning;
raw reasoning remains sensitive audit data.
