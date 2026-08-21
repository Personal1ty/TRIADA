# Desktop Observatory UI — Design Specification

## Goal

Transform `/ui` from a multi-tab developer dashboard into a full-size desktop
operator console for autonomous TRIADA runs. The operator should need only
three explicit actions:

1. configure the LLM API token;
2. submit a task to the swarm;
3. approve a risky action or task when the policy requires human approval.

All other runtime activity remains autonomous and observable.

## Role model

The Orchestrator remains an LLM agent. Its special status comes from its
contract, not from being a deterministic script: it proposes a plan and route,
while deterministic runtime checks validate capabilities, contracts, risk,
budgets, and approvals.

The UI must make this distinction visible:

- Orchestrator: LLM planning and routing;
- specialized agents: research, architecture, memory, criticism, exploration,
  and synthesis;
- Worker: bounded tool execution and artifact production;
- Auditor: evidence verification and quality gate;
- human: only explicit approvals and final review when required.

## Desktop layout

The page uses the whole available viewport with no fixed narrow content column.
It has four visual regions:

```text
┌─────────────────────────────────────────────────────────────────────┐
│ TRIADA Observatory     runtime status       LLM API   + New task    │
├───────────────┬───────────────────────────────────┬─────────────────┤
│ Runs          │ Execution graph                  │ Contracts       │
│               │                                   │                 │
│ task list     │ Orchestrator → agents → Worker   │ active contracts│
│ statuses      │                 → Auditor        │ policy state     │
│               │                                   │ approval action │
├───────────────┴───────────────────────────────────┴─────────────────┤
│ Result and latest append-only events                                │
└─────────────────────────────────────────────────────────────────────┘
```

### Header

The header contains the TRIADA identity, autonomous-runtime status, an LLM API
configuration action, and the task submission action. Existing configuration
controls remain available through the LLM API action rather than occupying the
main workspace.

### Runs column

Shows recent and active tasks with compact status, task id, elapsed time, and
agent count. Selecting a run updates the graph, contracts, result, and event
stream. The list must remain usable without opening separate tabs.

### Execution graph

The graph is the primary Observatory surface. It shows the selected task's
actual agent nodes and route edges from the API, not a decorative static graph.
Nodes expose role, agent id, state, and latest public thinking summary. Edges
show route purpose and active/waiting/completed state. Raw reasoning remains
hidden by default and is not rendered in the graph.

The first implementation may use SVG with deterministic positioning. The graph
adapter must keep node and edge data separate from layout so a later Obsidian-
style canvas or graph renderer can reuse the same API projection.

### Contracts column

Shows active contracts for the selected run, at minimum:

- research contract;
- execution contract;
- context packet and attached memory sources;
- approval/policy state;
- resource budget when present.

Contracts are read-only during execution. Editing remains an optional advanced
surface and is not part of the primary operator flow.

### Result and event region

The bottom region shows the current result or a clear in-progress state,
evidence/coverage indicators for research tasks, and the latest append-only
events. It must provide a direct way to understand what the swarm produced and
what it is waiting for.

## Interaction rules

- `LLM API` opens the existing provider configuration form in a compact modal
  or drawer.
- `+ New task` opens the minimal task form: goal, optional acceptance criteria,
  and tool policy only when the operator chooses advanced options.
- Approval controls appear only when the selected task has an actionable
  approval request.
- Background polling remains automatic and stops on terminal states.
- No manual refresh, raw reasoning, contract editing, or diagnostic tabs appear
  in the primary view. They may remain accessible as an advanced drawer.

## Runtime/API boundary

This UI change does not move orchestration into the browser. The browser only
submits commands and renders projections. The server remains responsible for:

- LLM calls and model routing;
- tool execution and PolicyGate checks;
- append-only audit events;
- memory and evidence projections;
- approval transitions;
- task timeouts and recovery.

The existing API projections should be reused and extended only where the
desktop graph needs missing state. No raw model reasoning is sent to the
public UI projection.

## Responsive behavior

- At desktop widths, use a three-column workspace and a bottom result/event
  band.
- At medium widths, collapse the contracts column into a drawer while keeping
  runs and graph visible.
- At narrow widths, use a single-column stack with graph first, then contracts,
  then result/events.
- The page itself must not have horizontal overflow.

## Acceptance criteria

- `/ui` fills the desktop viewport and does not constrain the main content to a
  narrow centered column.
- The primary screen exposes only LLM API, New task, and conditional approval
  actions.
- A selected task renders its actual graph, current contracts, result, and
  latest events without switching tabs.
- A running task updates automatically; terminal tasks stop polling.
- Approval can be completed from the primary screen and the task continues
  without re-planning an already approved plan.
- Raw reasoning remains opt-in and absent from normal UI payloads.
- Existing API behavior and safety gates remain intact.
- Focused UI/API tests and the complete test suite pass.

## Next stage

After this UI slice is stable, implement the hybrid agent catalog and routing:
deterministic role contracts select the allowed specialized-agent set, the LLM
Orchestrator proposes a route, and the runtime validates and records the
approved route. The desktop graph will then render those specialized roles
without another UI redesign.
