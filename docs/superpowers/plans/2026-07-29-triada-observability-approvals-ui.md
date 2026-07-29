# TRIADA Observability And Approvals UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add filtered audit-event observability and an approval queue to the local TRIADA UI while keeping raw reasoning hidden by default.

**Architecture:** Reuse the existing `audit_events` stream and `TaskService` instead of adding new storage. `/v1/tasks/{task_id}/events` gets safe filters and sensitive-redaction defaults; `/v1/tasks?status=waiting_approval` powers the approval queue. The UI adds tabs and approval controls on top of the existing single-file dashboard.

**Tech Stack:** FastAPI, Pydantic response schemas, existing audit projection helpers, static HTML/CSS/JS, pytest/httpx ASGI tests.

---

### Task 1: Filtered Audit Events API

**Files:**
- Modify: `app/api/routes.py`
- Modify: `app/schemas/tasks.py`
- Test: `tests/triada/test_api_sse.py`

- [x] Write failing tests for event filters: `event_type`, `agent_id`, `trace_id`, and default sensitive redaction.
- [x] Run `python3 -m pytest tests/triada/test_api_sse.py::test_task_events_can_be_filtered_without_sensitive_payloads -q` and verify it fails.
- [x] Add query params to `GET /v1/tasks/{task_id}/events`, filter in-memory events for the task trace, reject mismatched `trace_id` with 404 or empty result according to existing task ownership semantics, and keep `events_to_public_response`.
- [x] Add `raw_reasoning_refs` for `model_reasoning_content_captured` events without returning `raw_reasoning_content` unless a later explicit raw endpoint is added.
- [x] Run the focused API tests.

### Task 2: Waiting Approval Task List API

**Files:**
- Modify: `app/api/routes.py`
- Modify: `app/services/task_service.py`
- Test: `tests/triada/test_api_sse.py`

- [x] Write a failing test for `GET /v1/tasks?status=waiting_approval`.
- [x] Run the specific test and verify it fails.
- [x] Add optional `status` filter to task listing.
- [x] Keep default `/v1/tasks` behavior unchanged.
- [x] Run focused API tests.

### Task 3: Approval Queue UI

**Files:**
- Modify: `app/ui/index.html`
- Test: `tests/triada/test_local_ui.py`

- [x] Write failing static UI tests for tabs and approval queue controls.
- [x] Run `python3 -m pytest tests/triada/test_local_ui.py::test_get_local_swarm_ui -q` and verify it fails.
- [x] Add tabs: `Runs`, `Thinking`, `Raw Reasoning`, `Contracts`, `Approvals`.
- [x] Add approval queue panel that calls `GET /v1/tasks?status=waiting_approval`.
- [x] Add `Approve` button that calls `POST /v1/tasks/{task_id}/approve`, then refreshes the queue and selected task.
- [x] Keep raw reasoning tab locked with explicit sensitive-data notice; do not render raw reasoning payloads in this increment.
- [x] Run UI tests.

### Task 4: Documentation And Verification

**Files:**
- Modify: `README.md`
- Modify: `/Users/hidanhidanov/obsidian-mind/work/active/TRIADA UI v1.md`
- Modify: `/Users/hidanhidanov/obsidian-mind/work/projects/triada.md`

- [x] Update README API/UI docs.
- [x] Run `python3 -m pytest tests/triada/test_api_sse.py tests/triada/test_local_ui.py tests/triada/test_api_swarm_ui.py -q`.
- [x] Run `python3 -m pytest -q`.
- [x] Update Obsidian context with the pushed commit and next remaining items.
