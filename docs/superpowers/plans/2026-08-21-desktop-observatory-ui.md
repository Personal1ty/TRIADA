# Desktop Observatory UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the narrow multi-tab `/ui` with a full-size desktop Observatory that exposes only LLM configuration, task submission, conditional approval, live graph, contracts, result, and append-only events.

**Architecture:** Keep all orchestration, routing, memory, policy, tool execution, and approvals on the server. The browser becomes a thin projection layer: one selected task drives a three-column desktop workspace and a bottom result/event band. Reuse existing task, swarm-graph, contract, memory, research, usage, and event endpoints; add only projections that are proven missing by focused tests.

**Tech Stack:** FastAPI/Jinja-style static HTML response, vanilla HTML/CSS/JavaScript, existing JSON APIs, pytest, JavaScript syntax check, local browser smoke testing.

---

## File map

- Modify: `/Users/hidanhidanov/triada/app/ui/index.html` — desktop shell, minimal actions, graph, contracts, result, polling, and drawers.
- Modify only if required: `/Users/hidanhidanov/triada/app/api/routes.py` — missing compact task/run projection or approval response.
- Modify only if required: `/Users/hidanhidanov/triada/app/services/task_service.py` — preserve background polling and terminal transitions; no behavior change unless a UI flow exposes a regression.
- Test: `/Users/hidanhidanov/triada/tests/triada/test_local_ui.py` — required primary controls and removal of primary diagnostic tabs.
- Test: `/Users/hidanhidanov/triada/tests/triada/test_api_swarm_ui.py` — selected-task projections, graph data, and approval continuation.
- Documentation: `/Users/hidanhidanov/triada/README.md` — update `/ui` operator flow and verification commands.
- Context: `/Users/hidanhidanov/obsidian-mind/work/projects/triada.md` — record the shipped layout, tests, commit, and remaining advanced surfaces after implementation.

### Task 1: Lock the current UI/API contract with failing tests

**Files:**
- Modify: `/Users/hidanhidanov/triada/tests/triada/test_local_ui.py`
- Modify: the existing task API test file found with `rg -l "run_async|approve" tests/triada`

- [ ] **Step 1: Inspect existing UI and API assertions**

Run:

```bash
rg -n "Runs|Thinking|Raw Reasoning|Contracts|Approvals|run_async|approve|swarm-graph" app/ui/index.html tests/triada
```

Record the existing endpoint names and test fixture shape before changing selectors.

- [ ] **Step 2: Add failing UI assertions for the primary operator surface**

Add assertions equivalent to:

```python
assert "TRIADA Observatory" in response.text
assert "LLM API" in response.text
assert "New task" in response.text or "+ New task" in response.text
assert "Execution graph" in response.text
assert "Contracts" in response.text
assert "Result" in response.text
assert "/v1/tasks/" in response.text
```

Keep API endpoint compatibility assertions for `/run_async`, `/approve`, and
`/swarm-graph`.

- [ ] **Step 3: Run the focused tests and confirm the new assertions fail**

Run:

```bash
python3 -m pytest -q tests/triada/test_local_ui.py
```

Expected: failure because the current HTML still presents the old tab-first layout.

- [ ] **Step 4: Commit the contract tests**

```bash
git add tests/triada/test_local_ui.py
git commit -m "test: define desktop observatory ui contract"
```

Stage only the exact test files changed in this task.

### Task 2: Build the desktop shell and minimal operator actions

**Files:**
- Modify: `/Users/hidanhidanov/triada/app/ui/index.html`
- Test: `/Users/hidanhidanov/triada/tests/triada/test_local_ui.py`

- [ ] **Step 1: Replace the narrow page layout with viewport grid primitives**

Implement these layout invariants in the existing stylesheet:

```css
html, body { min-height: 100%; }
body { min-width: 0; overflow-x: hidden; }
main { width: 100%; max-width: none; margin: 0; padding: 12px; }
.desktop-shell { min-height: 100vh; display: grid; grid-template-rows: auto minmax(0, 1fr) auto; }
.desktop-workspace { min-height: 0; display: grid; grid-template-columns: 260px minmax(0, 1fr) 320px; gap: 12px; }
```

Add breakpoint rules that collapse the right column and then the full grid at
medium and narrow widths, without page-level horizontal overflow.

- [ ] **Step 2: Reduce the visible actions to three states**

Keep only these primary controls in the header and selected-task area:

```html
<button id="open-llm-config" type="button">LLM API</button>
<button id="new-task" type="button">+ New task</button>
<button id="approve-task" type="button" hidden>Approve action</button>
```

Move diagnostic controls (raw reasoning, contract editor, manual refresh,
advanced filters) into a hidden advanced drawer or remove them from the main
surface. Do not remove their server endpoints.

- [ ] **Step 3: Run focused UI tests**

```bash
python3 -m pytest -q tests/triada/test_local_ui.py
```

Expected: the desktop-shell and primary-action assertions pass.

- [ ] **Step 4: Commit the shell**

```bash
git add app/ui/index.html tests/triada/test_local_ui.py
git commit -m "feat: add desktop observatory shell"
```

### Task 3: Render live runs, graph, contracts, result, and events in one view

**Files:**
- Modify: `/Users/hidanhidanov/triada/app/ui/index.html`
- Modify only if a response field is missing: `/Users/hidanhidanov/triada/app/api/routes.py`
- Test: `/Users/hidanhidanov/triada/tests/triada/test_local_ui.py`
- Test: the existing swarm graph/API test file found with `rg -l "swarm-graph" tests/triada`

- [ ] **Step 1: Add stable DOM anchors for the four regions**

Use these IDs so rendering and browser smoke tests do not depend on visual text:

```html
<section id="runs-panel"></section>
<section id="execution-graph-panel"><svg id="execution-graph"></svg></section>
<aside id="contracts-panel"></aside>
<section id="result-panel"></section>
<section id="events-panel"></section>
```

- [ ] **Step 2: Implement pure graph projection helpers in the existing page script**

The helpers must accept API data and return DOM-safe projections:

```javascript
function graphLayout(nodes, edges) {
  const order = { orchestrator: 0, researcher: 1, architect: 1, explorer: 1,
    librarian: 1, critic: 1, synthesizer: 2, worker: 2, auditor: 3 };
  return [...nodes].sort((a, b) => (order[a.role] ?? 2) - (order[b.role] ?? 2))
    .map((node, index) => ({ ...node, x: 80 + (index % 4) * 190, y: 70 + Math.floor(index / 4) * 110 }));
}
```

Render actual node ids, roles, status, route purposes, and active state from
`/v1/tasks/{task_id}/swarm-graph`; never hard-code the runtime graph.

- [ ] **Step 3: Connect contracts and result projections**

For the selected task, render existing research, execution, memory/context,
economics, and approval data. If a projection is unavailable, show a named
`Not available for this run` state instead of hiding the panel or inventing a
value. Escape all model/task/event text through the existing HTML escaping
helper before insertion.

- [ ] **Step 4: Keep background polling automatic**

The selected task loop must refresh runs, graph, contracts, result, and events
using the existing polling mechanism. Stop polling for:

```javascript
const terminalStatuses = new Set([
  "completed", "failed", "blocked", "cancelled", "timed_out"
]);
```

Do not reintroduce a manual-refresh dependency for normal operation.

- [ ] **Step 5: Run UI and graph tests**

```bash
python3 -m pytest -q tests/triada/test_local_ui.py tests/triada/test_api_swarm_ui.py tests/triada/test_graph_adapter.py
```

- [ ] **Step 6: Commit the live Observatory**

```bash
git add app/ui/index.html app/api/routes.py tests/triada
git commit -m "feat: render live graph contracts and results"
```

### Task 4: Integrate minimal task submission and approval drawers

**Files:**
- Modify: `/Users/hidanhidanov/triada/app/ui/index.html`
- Modify only if needed: `/Users/hidanhidanov/triada/app/api/routes.py`
- Test: `/Users/hidanhidanov/triada/tests/triada/test_local_ui.py`
- Test: existing task action tests found with `rg -l "approve|run_async" tests/triada`

- [ ] **Step 1: Add a minimal New task form**

The default form contains goal and acceptance criteria. Keep tool policy and
risk fields under an explicit advanced disclosure. Submit through the existing
task creation endpoint, then call `/v1/tasks/{task_id}/run_async` and select
the returned task.

- [ ] **Step 2: Add the LLM API drawer**

Reuse the existing provider fields and save/test actions, but render them only
when `LLM API` is opened. Preserve token masking and the existing clear-token
behavior. Never expose the saved token in page text or API responses.

- [ ] **Step 3: Add conditional approval**

Show `Approve action` only when the selected task status is
`waiting_approval` and the API reports an actionable pending approval. On
approval, call the existing approve endpoint, close the drawer, and resume the
selected task without asking the Orchestrator for a new plan.

- [ ] **Step 4: Test the action flow**

```bash
python3 -m pytest -q tests/triada/test_local_ui.py tests/triada/test_api_swarm_ui.py
```

Expected: task creation, background start, approval continuation, and token
redaction tests remain green.

- [ ] **Step 5: Commit the operator actions**

```bash
git add app/ui/index.html app/api/routes.py tests/triada
git commit -m "feat: add minimal task and approval actions"
```

### Task 5: Browser smoke, documentation, and durable context

**Files:**
- Modify: `/Users/hidanhidanov/triada/README.md`
- Modify: `/Users/hidanhidanov/obsidian-mind/work/projects/triada.md`
- Test/inspect: `/Users/hidanhidanov/triada/app/ui/index.html`

- [ ] **Step 1: Run static checks**

```bash
python3 -m pytest -q
node --check /tmp/triada-ui-script.js
git diff --check
```

Before the command, extract the single `<script>` block from
`app/ui/index.html` to `/tmp/triada-ui-script.js`; do not add that temporary
file to the repository.

- [ ] **Step 2: Run browser smoke at desktop and narrow widths**

Verify against `http://127.0.0.1:8000/ui`:

- desktop viewport uses the full width;
- no horizontal overflow;
- header exposes only LLM API and New task until approval is needed;
- selected task updates graph/contracts/result/events;
- approval action appears only for a waiting task;
- narrow viewport collapses without clipped controls;
- browser console has no errors.

- [ ] **Step 3: Update README**

Document the operator flow:

```text
open /ui → configure LLM API once → create task → observe graph/contracts/result
→ approve only requested actions → review final result
```

- [ ] **Step 4: Update Obsidian work context**

Add 5–10 bullets to the TRIADA project note covering the final layout, changed
files, test commands, commit ids, and the next specialized-agent routing step.
Do not copy raw logs or secrets.

- [ ] **Step 5: Commit documentation and report validation**

```bash
git add README.md
git commit -m "docs: document desktop observatory workflow"
```

The Obsidian vault remains a separate repository and must not be included in
the TRIADA commit.

## Self-review

- Desktop full-size layout: Task 2.
- Minimal actions: Tasks 2 and 4.
- Actual graph and Obsidian-compatible node/edge projection: Task 3.
- Contracts during execution: Task 3.
- Result and append-only events: Task 3.
- Autonomous polling and server-side safety: Tasks 3 and 4.
- Responsive behavior: Task 2 plus Task 5 browser smoke.
- Specialized-agent catalog/routing: explicitly deferred to the next stage in
  the approved design, so it does not silently expand this UI plan.
