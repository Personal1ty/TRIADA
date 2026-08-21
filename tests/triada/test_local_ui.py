from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
import tomllib

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@asynccontextmanager
async def _client() -> AsyncIterator[AsyncClient]:
    app = create_app(testing=True)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client


@pytest.mark.asyncio
async def test_get_local_swarm_ui():
    async with _client() as client:
        response = await client.get("/ui")

    assert response.status_code == 200
    assert "TRIADA Observatory" in response.text
    assert "LLM API" in response.text
    assert "New task" in response.text or "+ New task" in response.text
    assert "Execution graph" in response.text
    assert "Contracts" in response.text
    assert "Result" in response.text
    assert 'class="desktop-shell"' in response.text
    assert "desktop-workspace" in response.text
    assert "grid-template-columns: 260px minmax(0, 1fr)" in response.text
    assert "@media (max-width: 1100px)" in response.text
    assert "@media (max-width: 720px)" in response.text
    assert 'id="open-llm-config" type="button" aria-controls="llm-config" aria-expanded="false">LLM API' in response.text
    assert 'id="new-task" type="button" aria-controls="create-task-form" aria-expanded="false">+ New task' in response.text
    assert 'id="approve-task" type="button" hidden>Approve action' in response.text
    assert 'class="advanced-drawer" id="advanced-drawer" hidden' in response.text
    assert '.advanced-drawer.is-open' in response.text
    hidden_css = response.text.partition('\n    [hidden] {')[2].partition('}')[0]
    assert 'display: none !important;' in hidden_css
    assert 'id="toggle-advanced" type="button" aria-controls="advanced-drawer" aria-expanded="false">Advanced</button>' in response.text
    assert 'advancedToggleButton.addEventListener("click"' in response.text
    assert '<nav class="tabs" aria-label="TRIADA dashboard views">' in response.text
    assert '<section id="llm-config" role="dialog" aria-modal="true" aria-labelledby="llm-config-title" hidden>' in response.text
    assert '<form id="create-task-form" class="form-grid" hidden>' in response.text
    assert '<h2 id="llm-config-title">LLM Provider</h2>' in response.text
    assert 'id="close-llm-config" type="button"' in response.text
    assert 'id="task-advanced"' in response.text
    assert '<form class="controls" id="task-form" hidden>' in response.text
    assert '<summary>Advanced options</summary>' in response.text
    assert 'id="task-risk"' in response.text
    assert 'createTask(true);' in response.text
    criteria_control = response.text.partition('id="task-criteria"')[2].partition('</div>')[0]
    assert 'required' not in criteria_control
    assert 'value="return useful result"' not in criteria_control
    assert 'acceptance_criteria: parseList(taskCriteria.value)' in response.text
    assert 'createRunTaskButton.addEventListener("click", () => {' in response.text
    assert 'createTask(false);' in response.text
    create_task_body = response.text.partition('async function createTask(runAfterCreate)')[2].partition('async function runCurrentTask')[0]
    assert 'taskCreateInFlight = false;\n        createTaskButton.disabled = false;\n        createRunTaskButton.disabled = false;' in create_task_body
    assert 'id="raw-reasoning-view" hidden' in response.text
    assert 'id="contracts-view" hidden' in response.text
    assert 'id="approvals-view" hidden' in response.text
    assert 'id="toggle-contracts"' not in response.text
    assert 'id="run-contracts-tab"' in response.text
    assert 'min-width: 720px' not in response.text
    assert 'preserveAspectRatio="xMidYMin meet"' in response.text
    assert 'function setPanelOpen' in response.text
    assert 'panel.hidden = !open;' in response.text
    assert 'trigger.setAttribute("aria-expanded", String(open));' in response.text
    assert 'trigger.focus();' in response.text
    assert 'if (!advancedDrawer.hidden && event.key === "Escape")' in response.text
    assert 'setPanelOpen(advancedToggleButton, advancedDrawer, false);' in response.text
    assert "/v1/tasks/" in response.text
    assert "/swarm-graph" in response.text
    assert "TRIADA Swarm" in response.text
    assert "/v1/swarm/contract" in response.text
    assert "/v1/llm/config" in response.text
    assert "/v1/llm/test" in response.text
    assert 'id="graph"' in response.text
    assert 'id="execution-graph-panel"' in response.text
    assert 'data-observatory-panel="execution-graph-panel"' in response.text
    assert 'id="execution-graph"' in response.text
    assert response.text.count('id="execution-graph"') == 1
    assert 'id="run-observatory"' in response.text
    assert 'id="result-panel"' in response.text
    assert 'id="runs-panel"' in response.text
    assert 'id="observatory-timeline"' in response.text
    assert 'id="observatory-inspector"' in response.text
    assert 'id="observatory-evidence"' in response.text
    assert 'id="observatory-pass-rate"' in response.text
    assert 'id="observatory-replay"' in response.text
    assert 'id="observatory-checkpoints"' in response.text
    assert 'id="observatory-checkpoint-list"' in response.text
    assert 'class="replay-task"' in response.text
    assert "/replay" in response.text
    assert "/v1/tasks/${encodeURIComponent(requestedTaskId)}/quality" in response.text
    assert "/v1/tasks/${encodeURIComponent(requestedTaskId)}/checkpoints" in response.text
    assert "/v1/tasks/${encodeURIComponent(requestedTaskId)}/inspector" in response.text
    assert "renderRunObservatory" in response.text
    assert 'id="graph-summary"' in response.text
    assert 'id="graph-route-list"' in response.text
    assert 'class="graph-node-meta"' in response.text
    assert 'id="contracts"' in response.text
    assert 'data-observatory-panel="contracts-panel"' in response.text
    assert 'id="selected-research-contract"' in response.text
    assert 'id="selected-execution-contract"' in response.text
    assert 'id="selected-context-sources"' in response.text
    assert 'id="selected-approval-state"' in response.text
    assert 'id="selected-resource-budget"' in response.text
    assert 'id="thinking"' in response.text
    assert 'id="memory"' in response.text
    assert 'id="memory-query"' in response.text
    assert 'id="search-memory"' in response.text
    assert 'id="global-memory"' in response.text
    assert 'id="observatory-memory-backend"' in response.text
    assert 'id="observatory-budget"' in response.text
    assert 'id="memory-graph"' in response.text
    assert "/memory/graph" in response.text
    assert 'id="global-memory-graph-status"' in response.text
    assert 'id="research-plan"' in response.text
    assert 'id="research-evidence"' in response.text
    assert "/research" in response.text
    assert "/swarm/capabilities" in response.text
    assert "/capabilities/registry" in response.text
    assert 'id="parameter-influence"' in response.text
    assert "/research/influence" in response.text
    assert "/usage" in response.text
    assert 'id="playbook-runs"' in response.text
    assert "/playbook/runs" in response.text
    assert 'id="playbook-templates"' in response.text
    assert "/playbooks/templates" in response.text
    assert 'id="failure-catalog"' in response.text
    assert "/failures" in response.text
    assert 'id="decision-heuristics"' in response.text
    assert "/research/recommendations" in response.text
    assert 'id="playbook-benchmarks"' in response.text
    assert "/playbooks/benchmarks" in response.text
    assert "grid-template-columns: minmax(0, 1fr)" in response.text
    assert "#runs-view" in response.text
    assert 'id="search-global-memory"' in response.text
    assert "/v1/memory/search?q=" in response.text
    assert "/v1/tasks/${encodeURIComponent(taskId)}/memory" in response.text
    assert 'id="runs-tab"' in response.text
    assert 'id="thinking-tab"' in response.text
    assert 'id="raw-reasoning-tab"' in response.text
    assert 'id="contracts-tab"' in response.text
    assert 'id="approvals-tab"' in response.text
    assert 'id="approval-queue"' in response.text
    assert 'id="refresh-approvals"' in response.text
    assert 'class="approve-task"' in response.text
    assert 'id="raw-reasoning-locked"' in response.text
    assert 'id="raw-reasoning-ack"' in response.text
    assert 'id="raw-reasoning-refs"' in response.text
    assert 'class="reveal-raw-reasoning"' in response.text
    assert 'id="contract-version-select"' in response.text
    assert 'id="contract-diff-from"' in response.text
    assert 'id="contract-diff-to"' in response.text
    assert 'id="compare-contracts"' in response.text
    assert 'id="run-contracts-view"' in response.text
    assert "contract/diff?from_version=" in response.text
    assert 'id="contract-version"' in response.text
    assert 'id="contract-author"' in response.text
    assert 'id="contract-notes"' in response.text
    assert 'id="contract-change-reason"' in response.text
    assert 'id="contract-validation-errors"' in response.text
    assert 'id="chief-auditor-id"' in response.text
    assert 'id="chief-auditor-strict"' in response.text
    assert 'id="scaling-default-pairs"' in response.text
    assert 'id="scaling-min-pairs"' in response.text
    assert 'id="scaling-max-pairs"' in response.text
    assert 'id="worker-pair-editor"' in response.text
    assert 'id="add-worker-pair"' in response.text
    assert 'id="route-map-editor"' in response.text
    assert 'id="add-route-map-entry"' in response.text
    assert 'id="sync-contract-json"' in response.text
    assert 'id="contract-json"' in response.text
    assert 'id="contract-bodies"' in response.text
    assert 'class="contract-body-card"' in response.text
    assert 'class="contracts-layout"' in response.text
    assert 'class="contract-editor-column"' in response.text
    assert 'class="contract-inspector-column"' in response.text
    assert "@media (min-width: 1280px)" in response.text
    assert "max-width: 100%;" in response.text
    assert "width: min(440px, 48vw)" not in response.text
    assert "renderContractBodies" in response.text
    assert 'id="save-contract"' in response.text
    assert 'id="refresh-contract-versions"' in response.text
    assert 'id="llm-config"' in response.text
    assert 'id="llm-clear-api-key"' in response.text
    assert 'id="create-task-form"' in response.text
    assert "Tool policy / Ограничения инструментов" not in response.text
    assert 'id="task-tools"' not in response.text
    assert 'id="run-contracts-view"' in response.text
    assert 'data-tab-target="run-contracts-view"' in response.text
    assert '<nav class="tabs" aria-label="TRIADA dashboard views" hidden>' not in response.text
    assert response.text.index('id="contracts-panel"') > response.text.index('id="run-contracts-view"')
    assert 'id="demo-template-select"' in response.text
    assert 'id="load-demo-template"' in response.text
    assert 'id="run-demo-flow"' in response.text
    assert 'id="run-task"' in response.text
    assert 'let taskCreateInFlight = false;' in response.text
    assert 'if (taskCreateInFlight) {' in response.text
    assert 'let approvalInFlight = false;' in response.text
    assert 'if (approvalInFlight) {' in response.text
    assert 'approveTaskButton.disabled = true;' in response.text
    assert 'document.addEventListener("keydown"' in response.text
    assert 'event.key === "Escape"' in response.text
    assert 'event.key === "Tab"' in response.text
    assert 'function trapLlmDialogFocus' in response.text
    assert 'llmConfigPanel.querySelectorAll' in response.text
    assert 'closeLlmConfigButton.focus();' in response.text
    assert 'trigger.focus();' in response.text
    assert 'let refreshInFlight = false;' in response.text
    assert 'let refreshSequence = 0;' in response.text
    assert 'function isCurrentRefreshRequest' in response.text
    refresh_loader = response.text.partition('async function refreshCurrentTask(options = {})')[2].partition('async function loadTask')[0]
    assert 'if (refreshInFlight) {' in refresh_loader
    assert 'refreshInFlight = true;' in refresh_loader
    assert 'const refreshRequestSequence = ++refreshSequence;' in refresh_loader
    assert 'isCurrentRefreshRequest(requestedTaskId, requestGeneration, refreshRequestSequence)' in refresh_loader
    assert 'refreshInFlight = false;' in refresh_loader
    assert 'let contractLoadSequence = 0;' in response.text
    assert 'let contractRequestGeneration = 0;' in response.text
    assert 'let requestedContractVersion = "";' in response.text
    assert 'let contractVersionsInFlight = false;' in response.text
    assert 'let contractVersionsSequence = 0;' in response.text
    assert 'let contractDiffSequence = 0;' in response.text
    assert 'function isCurrentContractLoad' in response.text
    assert 'request.generation === contractRequestGeneration' in response.text
    assert 'function clearContractProjection' in response.text
    contract_versions_loader = response.text.partition('async function loadContractVersions(preferredVersionOverride = "", allowDuringContractAction = false)')[2].partition('async function compareContracts')[0]
    assert 'if (contractVersionsInFlight) {' in contract_versions_loader
    assert 'if (contractActionInFlight && !allowDuringContractAction)' in contract_versions_loader
    assert 'const versionsRequestSequence = ++contractVersionsSequence;' in contract_versions_loader
    assert 'if (versionsRequestSequence !== contractVersionsSequence)' in contract_versions_loader
    assert 'contractVersionsInFlight = false;' in contract_versions_loader
    assert 'const previousVersion = contractVersionSelect.value;' in contract_versions_loader
    assert 'versions.includes(preferredVersion)' in contract_versions_loader
    assert 'const selectedVersion =' in contract_versions_loader
    assert 'contractVersionSelect.value = selectedVersion;' in contract_versions_loader
    assert 'loadSelectedContractVersion();' in contract_versions_loader
    assert 'function syncContractVersionSelection' in response.text
    assert 'const preferredVersion = preferredVersionOverride || previousVersion;' in contract_versions_loader
    default_contract_loader = response.text.partition('async function loadContract()')[2].partition('async function loadContractVersions')[0]
    assert 'clearContractProjection' in default_contract_loader
    contract_loader = response.text.partition('async function loadSelectedContractVersion()')[2].partition('async function saveContract')[0]
    assert 'if (contractActionInFlight) {' in contract_loader
    assert 'return;' in contract_loader
    assert 'try {' in contract_loader
    assert 'const contractRequest = beginContractLoad(version);' in contract_loader
    assert 'isCurrentContractLoad(contractRequest)' in contract_loader
    assert 'clearContractProjection' in contract_loader
    assert 'Unable to load contract version:' in contract_loader
    assert 'let eventPageInFlight = false;' in response.text
    assert 'let eventProjectionSequence = 0;' in response.text
    assert 'function beginEventProjectionRequest' in response.text
    assert 'function isCurrentEventProjectionRequest' in response.text
    assert 'async function loadMoreEvents()' in response.text
    pagination_loader = response.text.partition('async function loadMoreEvents()')[2].partition('eventAutoRefresh.addEventListener')[0]
    assert 'if (eventPageInFlight) {' in pagination_loader
    assert 'eventPageInFlight = true;' in pagination_loader
    assert 'const eventRequestSequence = beginEventProjectionRequest();' in pagination_loader
    assert 'eventProjectionSequence: eventRequestSequence' in pagination_loader
    assert 'loadMoreEventsButton.disabled = true;' in pagination_loader
    assert 'eventPageInFlight = false;' in pagination_loader
    assert 'isCurrentEventProjectionRequest(taskId, generation, eventRequestSequence)' in pagination_loader
    refresh_loader = response.text.partition('async function refreshCurrentTask(options = {})')[2].partition('async function loadTask')[0]
    assert 'const eventRequestSequence = beginEventProjectionRequest();' in refresh_loader
    assert 'eventProjectionSequence: eventRequestSequence' in refresh_loader
    assert 'isCurrentEventProjectionRequest(requestedTaskId, requestGeneration, eventRequestSequence)' in refresh_loader
    events_loader = response.text.partition('async function loadEvents(taskId, options = {})')[2].partition('async function loadMoreEvents')[0]
    assert 'options.eventProjectionSequence != null' in events_loader
    assert 'isCurrentEventProjectionRequest(taskId, options.generation, options.eventProjectionSequence)' in events_loader
    assert 'loadMoreEvents();' in response.text
    assert 'let contractActionInFlight = false;' in response.text
    assert 'let contractActionSequence = 0;' in response.text
    contract_save_loader = response.text.partition('async function saveContract()')[2].partition('function renderDemoTemplates')[0]
    assert 'if (contractActionInFlight) {' in contract_save_loader
    assert 'const actionSequence = ++contractActionSequence;' in contract_save_loader
    assert 'if (actionSequence !== contractActionSequence)' in contract_save_loader
    assert 'saveContractButton.disabled = true;' in contract_save_loader
    assert 'saveContractButton.disabled = false;' in contract_save_loader
    assert 'invalidateContractRequest();' in contract_save_loader
    assert 'invalidateContractVersionsRequest();' in contract_save_loader
    assert 'await loadContractVersions(savedContract.contract_version, true);' in contract_save_loader
    assert 'syncContractVersionSelection(savedContract);' in contract_save_loader
    assert 'syncContractVersionSelection(savedContract);' in contract_save_loader.partition('await loadContractVersions(savedContract.contract_version, true);')[2]
    diff_loader = response.text.partition('async function compareContracts()')[2].partition('async function requestReplay')[0]
    assert 'const diffRequestSequence = ++contractDiffSequence;' in diff_loader
    assert 'if (diffRequestSequence !== contractDiffSequence)' in diff_loader
    assert 'let llmActionInFlight = false;' in response.text
    assert 'let llmActionSequence = 0;' in response.text
    llm_save_loader = response.text.partition('async function saveLlmConfig()')[2].partition('async function testLlmConfig')[0]
    llm_test_loader = response.text.partition('async function testLlmConfig()')[2].partition('function contractRef')[0]
    for action_loader in (llm_save_loader, llm_test_loader):
        assert 'if (llmActionInFlight) {' in action_loader
        assert 'const actionSequence = ++llmActionSequence;' in action_loader
        assert 'if (actionSequence !== llmActionSequence)' in action_loader
    assert 'function setLlmActionBusy(busy)' in response.text
    assert 'saveLlmButton.disabled = busy;' in response.text
    assert 'testLlmButton.disabled = busy;' in response.text
    assert 'let rawReasoningRevealSequence = 0;' in response.text
    raw_reasoning_loader = response.text.partition('async function revealRawReasoning(eventId)')[2].partition('function clearRawReasoningReveal')[0]
    assert 'const rawReasoningRequestSequence = ++rawReasoningRevealSequence;' in raw_reasoning_loader
    assert 'rawReasoningRequestSequence !== rawReasoningRevealSequence' in raw_reasoning_loader
    assert 'acknowledge_sensitive: rawReasoningAck.checked' in raw_reasoning_loader
    assert 'id="event-feed"' in response.text
    assert 'id="events-panel"' in response.text
    assert 'data-observatory-panel="events-panel"' in response.text
    assert 'id="event-auto-refresh"' in response.text
    assert 'id="event-auto-refresh" name="event-auto-refresh" type="checkbox" checked' in response.text
    assert 'const terminalStatuses = new Set(["completed", "failed", "blocked", "cancelled", "corrections_required", "timed_out"])' in response.text
    assert 'id="refresh-events"' in response.text
    events_section = response.text.partition('<section id="events"')[2].partition('</section>')[0]
    assert 'id="refresh-events"' not in events_section
    advanced_drawer = response.text.partition('<div class="advanced-drawer" id="advanced-drawer"')[2].partition('<form class="controls" id="task-form"')[0]
    assert 'id="refresh-events"' in advanced_drawer
    assert 'id="load-more-events"' in response.text
    assert "after_event_id" in response.text
    assert 'fetchEventsPage(taskId, options.after_event_id || null, "desc")' in response.text
    assert '"waiting_approval"' not in response.text.partition("const terminalStatuses = new Set(")[2].partition(");")[0]
    assert "/v1/tasks" in response.text
    assert "/v1/tasks?status=waiting_approval" in response.text
    assert "/v1/demo/templates" in response.text
    assert "/v1/demo/run" in response.text
    assert "/approve" in response.text
    assert "/raw-reasoning/" in response.text
    assert 'window.location.protocol === "file:"' in response.text
    assert "http://127.0.0.1:8000/ui" in response.text
    assert "/v1/swarm/contracts" in response.text
    assert "/run_async" in response.text
    assert 'await postJson(`/v1/tasks/${encodeURIComponent(approvalTaskId)}/run_async`, {});' in response.text
    approval_loader = response.text.partition('async function approveTask(taskId)')[2].partition('async function revealRawReasoning')[0]
    approval_lifecycle = approval_loader.partition('await postJson(`/v1/tasks/${encodeURIComponent(approvalTaskId)}/approve`')[2].partition('await postJson(`/v1/tasks/${encodeURIComponent(approvalTaskId)}/run_async`, {});')[0]
    assert 'const approvalTaskId = String(taskId);' in approval_loader
    assert 'isCurrentProjectionRequest' not in approval_lifecycle
    runs_view = response.text.partition('id="runs-view"')[2].partition('id="thinking-view"')[0]
    assert 'id="graph"' in runs_view
    assert 'id="events"' in runs_view
    load_task_body = response.text.partition("async function loadTask(taskId)")[2].partition("async function createTask")[0]
    assert "clearRawReasoningReveal();" in load_task_body
    assert "validateContractForm" in response.text
    assert "routesFromEditor" in response.text
    assert "runSelectedDemoFlow" in response.text
    assert "graph-lane-label" in response.text
    assert "node-worker" in response.text
    assert "projectExecutionGraph" in response.text
    assert "data-node-state" in response.text
    assert "data-edge-purpose" in response.text
    assert "renderSelectedContracts" in response.text
    assert "renderSelectedResult" in response.text
    assert "Not available for this run" in response.text
    assert "function hasPendingApproval(task, eventsPayload)" in response.text
    assert '["approval_required", "replay_waiting_approval"]' in response.text
    assert 'task?.status !== "waiting_approval"' in response.text
    assert "approveTaskButton.hidden = !hasPendingApproval(task, eventsPayload);" in response.text
    assert "MAX_PROJECTION_EVENT_PAGES" in response.text
    assert 'const MAX_PROJECTION_EVENT_PAGES = 10;' in response.text
    assert "loadProjectionEvents" in response.text
    assert "pageCount < MAX_PROJECTION_EVENT_PAGES" in response.text
    assert 'new URLSearchParams({ limit: "100", order })' in response.text
    assert 'params.set("order", order);' in response.text
    assert 'fetchEventsPage(projectionTaskId, null, "desc")' in response.text
    assert 'const MAX_LATEST_EVENT_PAGES = 1;' in response.text
    assert "events: events," in response.text
    assert "events: events.reverse()" not in response.text
    assert ".filter((event) => types.has(event.event_type))" in response.text
    assert "projectionGeneration" in response.text
    assert "isCurrentTaskRequest" in response.text
    assert "const requestToken = beginProjectionRequest();" in response.text
    assert "isCurrentTaskRequest(requestedTaskId, requestGeneration)" in response.text
    assert "isCurrentTaskRequest(created.task_id, requestToken)" in response.text
    assert "isCurrentTaskRequest(result.task.task_id, requestToken)" in response.text
    assert "const replayTaskId = String(currentTaskId);" in response.text
    assert 'let replayInFlight = false;' in response.text
    replay_loader = response.text.partition('async function requestReplay(eventId)')[2].partition('async function loadSelectedContractVersion')[0]
    assert 'if (replayInFlight) {' in replay_loader
    assert 'replayInFlight = true;' in replay_loader
    assert 'replayInFlight = false;' in replay_loader
    assert 'replayButton.disabled = true;' in replay_loader
    assert 'replayButton.disabled = false;' in replay_loader
    assert "const replayGeneration = projectionGeneration;" in response.text
    assert "const rawReasoningTaskId = String(currentTaskId);" in response.text
    assert "const memoryTaskId = String(taskId);" in response.text
    assert "const approvalGeneration = projectionGeneration;" in response.text
    assert "isCurrentTaskRequest(replayTaskId, replayGeneration)" in response.text
    assert "isCurrentTaskRequest(rawReasoningTaskId, rawReasoningGeneration)" in response.text
    assert "isCurrentTaskRequest(memoryTaskId, memoryGeneration)" in response.text
    assert "isCurrentProjectionRequest(approvalGeneration)" in response.text
    assert 'let runInFlight = false;' in response.text
    run_loader = response.text.partition('async function runCurrentTask()')[2].partition('taskForm.addEventListener')[0]
    assert 'if (runInFlight) {' in run_loader
    assert 'runInFlight = true;' in run_loader
    assert 'runInFlight = false;' in run_loader
    create_loader = response.text.partition('async function createTask(runAfterCreate)')[2].partition('async function runCurrentTask')[0]
    create_lifecycle = create_loader.partition('const created = await postJson("/v1/tasks", {')[2].partition('await postJson(`/v1/tasks/${encodeURIComponent(createdTaskId)}/run_async`, {});')[0]
    assert 'createdTaskId = String(created.task_id);' in create_lifecycle
    assert 'isCurrentProjectionRequest' not in create_lifecycle
    assert 'isCurrentTaskRequest' not in create_lifecycle
    assert 'await postJson(`/v1/tasks/${encodeURIComponent(createdTaskId)}/run_async`, {});' in create_loader
    assert "shortGraphLabel" in response.text
    assert "<title>${escapeHtml(node.id)}" in response.text
    assert 'data-node-id="${escapeHtml(node.id)}"' in response.text
    assert 'data-edge-purpose="${escapeHtml(edge.purpose)}"' in response.text
    assert "Array.isArray(graph?.nodes) ? graph.nodes : []" in response.text
    assert "Array.isArray(graph?.edges) ? graph.edges : []" in response.text
    assert "escapeHtml(displayValue(value))" in response.text
    assert "Math.max(128, Math.min(190" in response.text
    assert "Array.isArray(payload?.deltas)" in response.text
    assert "Array.isArray(payload?.notes)" in response.text
    assert 'thinkingStatus.textContent = "Not available for this run."' in response.text
    assert 'memoryStatus.textContent = "Not available for this run."' in response.text
    assert "const safePayload = payload || {};" in response.text
    assert "Array.isArray(safePayload.events)" in response.text
    assert "Array.isArray(safePayload.raw_reasoning_refs)" in response.text
    assert "const firstPage = await fetchEventsPage(projectionTaskId, null, \"desc\");" in response.text
    assert 'if (currentTaskId == null || currentTaskId === "")' in response.text
    assert "function emptyEventsProjection()" in response.text
    assert 'const projectionTaskId = String(requestedTaskId);' in response.text
    assert 'const selectedTask = task || { task_id: requestedTaskId, status: "unknown" };' in response.text
    assert 'escapeHtml(item.tokens || 0)' in response.text
    assert 'escapeHtml(item.average_quality ?? 0)' in response.text
    assert 'escapeHtml(item.total_tokens || 0)' in response.text
    assert 'escapeHtml(item.tokens_per_quality || 0)' in response.text
    assert 'escapeHtml(item.duration_ms || 0)' in response.text
    assert 'escapeHtml(item.estimated_cost ?? 0)' in response.text
    assert '"task_recovered"' in response.text
    assert 'Recovered terminal state' in response.text


def test_local_swarm_ui_is_packaged():
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert Path("app/ui/__init__.py").is_file()
    assert project["tool"]["setuptools"]["package-data"]["app.ui"] == ["*.html"]
