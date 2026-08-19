# TRIADA Service Packaging Hypotheses

These are hypotheses to validate with measured playbook runs, not promises or
runtime policy.

| Package | User outcome | Required evidence | Guardrail |
| --- | --- | --- | --- |
| Research Swarm | reproducible evidence map and uncertainty report | quality, coverage, tokens/quality, replay delta | no hidden tool authority |
| Analysis Swarm | decision comparison with explicit assumptions | evidence coverage, audit pass rate, failure recurrence | auditor gate required |
| Design Swarm | options, tradeoffs, and validation plan | acceptance criteria, review latency, replay quality | human final gate |
| Swarm Observatory | operator visibility into bottlenecks and cost | utilization, stale knowledge, route/error metrics | read-only projection |

Validation sequence:

1. Run the same template at least three times.
2. Compare quality, cost, throughput, failures, and replay outcomes.
3. Keep a package only when the outcome is reproducible and its guardrails are
   explicit in the playbook contract.
