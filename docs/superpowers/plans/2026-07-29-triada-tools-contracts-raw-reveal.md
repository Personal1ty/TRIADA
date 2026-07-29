# TRIADA Tools Contracts Raw Reveal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add the next operator controls: explicit raw-reasoning reveal, local swarm contract save/load, and safe read-only tool support.

**Architecture:** Keep raw reasoning hidden by default and expose it only through a dedicated POST reveal endpoint with an explicit acknowledgement. Keep contract editing local/runtime-scoped for this increment by storing validated `SwarmContract` versions on `app.state`. Add read-only command support through the existing worker/tool adapter path while preserving approval requirements for non-read-only risk policies.

**Tech Stack:** FastAPI, Pydantic schemas, existing `SwarmContract` model, existing `ShellTool`/`GitTool`, static `/ui`, pytest/httpx ASGI tests.

---

### Task 1: Explicit Raw Reasoning Reveal

**Files:**
- Modify: `app/api/routes.py`
- Modify: `app/schemas/tasks.py`
- Test: `tests/triada/test_api_sse.py`

- [x] Write failing tests for denied reveal without acknowledgement and successful reveal with acknowledgement.
- [x] Implement `POST /v1/tasks/{task_id}/raw-reasoning/{event_id}/reveal`.
- [x] Verify event belongs to task trace and contains `raw_reasoning_content`.
- [x] Run focused API tests.

### Task 2: Runtime Contract Versions API

**Files:**
- Modify: `app/main.py`
- Modify: `app/api/routes.py`
- Test: `tests/triada/test_api_swarm_ui.py`

- [x] Write failing tests for saving a modified valid contract and loading it by version.
- [x] Implement runtime `app.state.swarm_contract_versions`.
- [x] Add `GET /v1/swarm/contracts` and `POST /v1/swarm/contract`.
- [x] Keep existing `GET /v1/swarm/contract` compatible.
- [x] Run focused contract API tests.

### Task 3: Safe Read-Only Tools

**Files:**
- Modify: `app/agents/worker.py`
- Modify: `app/services/execution_engine.py`
- Test: `tests/triada/test_agents_auditor.py`
- Test: `tests/triada/test_execution_engine_runtime.py`

- [x] Write failing worker tests for `pytest`, `rg`, `ls`, `cat`, and `sed`.
- [x] Add worker support for safe read-only command names.
- [x] Reject mutating flags such as `sed -i`.
- [x] Keep high-risk/write/destructive requests behind existing approval gate.
- [x] Run focused worker/runtime tests.

### Task 4: UI Controls And Verification

**Files:**
- Modify: `app/ui/index.html`
- Modify: `tests/triada/test_local_ui.py`
- Modify: `README.md`

- [x] Add static UI tests for raw reveal acknowledgement controls and contract editor controls.
- [x] Add raw reveal refs panel that requires an acknowledgement checkbox before reveal.
- [x] Add contract JSON editor with save/load version controls.
- [x] Document APIs and run full verification.
