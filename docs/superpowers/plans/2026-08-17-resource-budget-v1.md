# Resource Budget v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an auditable resource budget and allocation decision to each swarm run without changing existing task lifecycle behavior.

**Architecture:** Keep budget calculation pure in `app/services/resource_budget.py`. The execution engine asks it for an admission decision before worker execution and emits a public `resource_allocation_decided` event. Existing scheduler and contract scaling remain intact; this increment only records and enforces bounded token/time/branch/retry limits.

**Tech Stack:** Python 3.12+, Pydantic v2, existing SwarmContract, pytest/pytest-asyncio, append-only AuditEmitter.

**Progress:** Tasks 1–4 are implemented and verified. Task 5 remains the
documentation/release gate for this increment.

---

### Task 1: Define the budget decision contract

**Files:**
- Create: `app/services/resource_budget.py`
- Test: `tests/triada/test_resource_budget.py`

- [ ] **Step 1: Write failing tests** for a decision that admits work under budget, rejects exhausted branches, and reports a stable reason.

```python
def test_allocate_admits_work_inside_budget():
    decision = allocate_work(
        ResourceBudget(max_parallel_branches=2, max_retries=1, max_tokens=1000),
        ResourceUsage(active_branches=1, retries=0, tokens_used=200),
    )
    assert decision.admitted is True
    assert decision.reason == "within_budget"


def test_allocate_rejects_parallel_branch_overage():
    decision = allocate_work(
        ResourceBudget(max_parallel_branches=2, max_retries=1, max_tokens=1000),
        ResourceUsage(active_branches=2, retries=0, tokens_used=200),
    )
    assert decision.admitted is False
    assert decision.reason == "parallel_branches_exhausted"
```

- [ ] **Step 2: Run the focused test and confirm the expected import failure.**

Run: `python3 -m pytest -q tests/triada/test_resource_budget.py`

Expected: FAIL because `app.services.resource_budget` does not exist.

- [ ] **Step 3: Implement the minimal pure types and allocator.**

Use frozen dataclasses with non-negative validation. Check branch count first,
then retries, then token usage; return the first stable reason.

- [ ] **Step 4: Run the focused test.**

Run: `python3 -m pytest -q tests/triada/test_resource_budget.py`

Expected: PASS.

- [ ] **Step 5: Commit the pure contract.**

```bash
git add app/services/resource_budget.py tests/triada/test_resource_budget.py
git commit -m "feat: add resource budget allocation contract"
```

### Task 2: Add budget fields to the task contract

**Files:**
- Modify: `app/schemas/tasks.py`
- Modify: `app/contracts/models.py`
- Test: `tests/triada/test_resource_budget.py`

- [ ] **Step 1: Add a failing validation test** proving task budgets reject
negative values and preserve safe defaults.
- [ ] **Step 2: Run the focused test and observe the validation failure.**
- [ ] **Step 3: Add optional budget fields** with bounded defaults:
`max_parallel_branches=0`, `max_retries=0`, and `max_tokens=0` where zero
preserves existing behavior and means that particular resource is not bounded
by the task budget.
- [ ] **Step 4: Run focused contract/schema tests.**
- [ ] **Step 5: Commit the schema change.**

### Task 3: Emit allocation decisions from execution

**Files:**
- Modify: `app/services/execution_engine.py`
- Modify: `app/audit/projection.py`
- Test: `tests/triada/test_execution_engine.py`

- [ ] **Step 1: Add a failing engine test** for `resource_allocation_decided`
with `admitted`, `reason`, budget, and usage fields.
- [ ] **Step 2: Run the focused engine test and confirm it fails.**
- [ ] **Step 3: Call the pure allocator before each worker branch** and emit the
append-only event. A rejected branch must produce an auditable stop reason and
must not invoke the worker.
- [ ] **Step 4: Add a public projection** that counts admitted/rejected branches
and exposes current budget utilization without raw model reasoning.
- [ ] **Step 5: Run focused engine/projection tests.**
- [ ] **Step 6: Commit the execution integration.**

### Task 4: Expose budget status in the API and Run Observatory

**Files:**
- Modify: `app/api/routes.py`
- Modify: `app/ui/index.html`
- Test: `tests/triada/test_api_sse.py`
- Test: `tests/triada/test_local_ui.py`

- [ ] **Step 1: Add failing API/UI tests** for budget status and the allocation
decision event.
- [ ] **Step 2: Run the focused API/UI tests and confirm the expected failure.**
- [ ] **Step 3: Add `GET /v1/tasks/{task_id}/budget`** and a compact UI card with
budget, used, remaining, and the latest allocation reason.
- [ ] **Step 4: Run focused API/UI tests and JavaScript syntax validation.**
- [ ] **Step 5: Commit the observability slice.**

### Task 5: Documentation and release gate

**Files:**
- Modify: `README.md`
- Modify: `docs/SWARM_EVOLUTION_ROADMAP.md`
- Modify: `docs/TRIADA_PRODUCT_DIRECTION.md`

- [ ] **Step 1: Document budget fields, event schema, endpoint, and zero-value
semantics.**
- [ ] **Step 2: Run `python3 -m pytest -q`, `git diff --check`, and compileall.**
- [ ] **Step 3: Update Obsidian with files, tests, commit, and next phase.**
- [ ] **Step 4: Push the verified commits to `origin/main`.**

## Rollout gate

The increment is ready when existing tasks still complete or block exactly as
before, every worker admission has a budget event, rejected work is not started,
and the Run Observatory exposes the reason without revealing raw reasoning.
