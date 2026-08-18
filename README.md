# TRIADA

TRIADA is an auditable, domain-agnostic swarm runtime built around three roles:
Orchestrator, Worker, and Auditor. It can coordinate research, analysis,
design, and tool-backed execution while preserving explicit contracts,
append-only audit events, redaction, and deterministic fake LLM behavior for
local development.

## How It Works

```text
User / API / CLI
      |
      v
POST /v1/tasks
      |
      v
TaskService
- creates task
- persists task_created audit event
- starts run_once when requested
      |
      v
ExecutionEngine
- emits planning_started
- selects LLM provider from runtime config, then falls back to env:
  LLM_PROVIDER=fake                -> deterministic FakeLLMProvider
  LLM_PROVIDER=openai-compatible   -> local LLM / corp-coder endpoint
  LLM_PROVIDER=openai-responses    -> OpenAI Responses API
  LLM_PROVIDER=codex-bridge        -> Codex-operated demo bridge, no API key
- uses streaming model responses and separates public summaries from sensitive reasoning data
      |
      v
Orchestrator
- plans bounded steps
- classifies risk_policy
- keeps tools inside allowed_tools
      |
      +-------------------------------+
      | LLM unavailable?              |
      | -> emit llm_unavailable       |
      | -> task status = blocked      |
      +-------------------------------+
      |
      +-------------------------------+
      | high-risk / destructive?      |
      | -> emit approval_required     |
      | -> task status = waiting_approval
      | -> /v1/tasks/{id}/approve     |
      +-------------------------------+
      |
      v
Worker
- executes only the approved step through a bounded scheduler
- uses explicitly allowed domain tools and records evidence
- the repository includes minimal local adapters such as echo and git status
      |
      v
Auditor
- verifies worker evidence
- emits audit_verdict
      |
      v
Final task status
completed | corrections_required | blocked | failed

All important runtime facts are written as append-only audit events before they
are exposed through the API or SSE stream. TRIADA exposes public progress through
thinking_summary_delta records and treats raw model reasoning as sensitive audit
data in model_reasoning_content_captured events.

The active swarm contract drives runtime scaling: matching task-weight rules
select worker-auditor pairs and emit a `swarm_scaled` audit event before step
execution.
```

## Project Structure

```text
TRIADA
├── app/
│   ├── agents/          # Orchestrator, Worker, Auditor role logic
│   ├── api/             # FastAPI routes and SSE endpoints
│   ├── audit/           # Redaction, append-only repository, projections, validators
│   ├── contracts/       # Role and swarm contracts, default contract JSON
│   ├── events/          # Event schemas and in-process event bus
│   ├── llm/             # Fake, OpenAI-compatible, and OpenAI Responses providers
│   ├── persistence/     # SQLAlchemy models and async session factory
│   ├── schemas/         # API/task/enumeration schemas
│   ├── services/        # Task service, scheduler, heartbeat, supervision
│   ├── ui/              # Local swarm dashboard HTML
│   └── tools/           # Explicitly allowed tool adapters
├── alembic/             # Database migrations
├── tests/triada/        # TRIADA unit and integration tests
├── docs/superpowers/    # Design specs and implementation plans
├── docker-compose.yml   # API + PostgreSQL local runtime
└── pyproject.toml       # Package metadata and dependencies
```

## Quickstart

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e '.[test]'
python3 -m pytest -q
```

Start the API locally with the default SQLite database:

```bash
uvicorn app.main:create_app --factory --reload
```

Run with PostgreSQL through Docker Compose:

```bash
docker compose up --build
```

The Docker service uses `DATABASE_URL=postgresql+asyncpg://triada:triada@postgres:5432/triada`.
Local PostgreSQL uses the `pgvector/pgvector:pg16` image. Alembic migration
`0002_enable_pgvector` enables the vector extension for PostgreSQL and skips it
on SQLite. Migration `0003_swarm_contract_versions` stores configurable swarm
contract versions in the database. Migration `0004_memory_embeddings` creates
the optional secondary vector index; its dimensions follow
`MEMORY_EMBEDDING_DIMENSIONS` (default `64`).
The default non-Docker setting is `sqlite+aiosqlite:///./triada.db`.

If local port `5432` is already occupied, publish Postgres on another host port:

```bash
TRIADA_POSTGRES_PORT=5433 docker compose up -d postgres
export DATABASE_URL=postgresql+asyncpg://triada:triada@127.0.0.1:5433/triada
alembic upgrade head
```

Verify that pgvector is enabled in local PostgreSQL:

```bash
psql postgresql://triada:triada@127.0.0.1:5433/triada \
  -c "select extname from pg_extension where extname = 'vector';"
```

Expected result:

```text
 extname
---------
 vector
```

## Install

Runtime dependencies are declared in `pyproject.toml`. Test dependencies are in
the `test` extra.

```bash
python3 -m pip install -e .
python3 -m pip install -e '.[test]'
```

Copy `.env.example` to `.env` to override default settings. The fake provider is
the default and does not require an API key. You can also configure the active
LLM at runtime through `POST /v1/llm/config` or the local `/ui` dashboard.
Runtime config is saved under `.triada/secrets/`; API responses never return the
token and expose only `has_api_key`. Omitting `api_key` in `POST /v1/llm/config`
keeps the currently saved token; send `"clear_api_key": true` to remove it.
The local secret file is encrypted to avoid accidental plaintext storage in the
workspace, but it is not a replacement for an OS keychain or external secrets
manager.

OpenAI Responses API example:

```bash
export LLM_PROVIDER=openai-responses
export LLM_API_KEY=sk-...
export LLM_MODEL=<openai-responses-model>
# Optional override; defaults to https://api.openai.com/v1
export LLM_BASE_URL=https://api.openai.com/v1
```

OpenAI-compatible local/corp/DeepSeek-style example through API:

```bash
curl -sS -X POST http://127.0.0.1:8000/v1/llm/config \
  -H 'content-type: application/json' \
  -d '{
    "provider":"openai-compatible",
    "base_url":"http://127.0.0.1:11434/v1",
    "model":"deepseek-reasoner",
    "api_key":null
  }'

curl -sS -X POST http://127.0.0.1:8000/v1/llm/test
```

The Responses provider sends `stream=true` with `reasoning.summary=detailed`.
Streaming reasoning summary/text events are stored as sensitive
`model_reasoning_content_captured` audit events, while public progress remains
available through `thinking_summary_delta`.

Codex-operated demo example:

```bash
./run_codex_bridge.sh
```

The Codex bridge is for recording demos where a Codex chat acts as the operator
that drives TRIADA. It does not expose hidden Codex chain-of-thought. It stores
explicit Codex-authored reasoning notes through the same
`model_reasoning_content_captured` audit event path used by model providers.

To drive TRIADA from any clean Codex chat, start `./run_codex_bridge.sh` in a
terminal, then paste this prompt into the new chat:

```text
Работаем в /Users/hidanhidanov/triada.

TRIADA API уже запущена на http://127.0.0.1:8000 с LLM_PROVIDER=codex-bridge.

Создай TRIADA-задачу через API:
goal="Проверь текущее состояние git-репозитория TRIADA через git status и покажи, что thinking оркестратора и воркера записался в БД"
allowed_tools=["git"]
acceptance_criteria=["получен git status","thinking оркестратора записан в audit_events","thinking воркера записан в audit_events"]

Потом запусти /run_once, покажи /thinking-summary и SQL из triada.db по trace_id.
```

## API

The FastAPI application factory is `app.main:create_app`.

Core endpoints under `/v1`:

- `GET /v1/llm/config` returns public active LLM settings without the token.
- `POST /v1/llm/config` saves runtime provider, base URL, model, and optional token.
  Omit `api_key` to preserve the current token, or send `clear_api_key=true` to
  remove it.
- `POST /v1/llm/test` checks the currently configured provider.
- `GET /v1/swarm/contract` returns the active swarm contract. Optional
  `version=<contract_version>` loads a saved version.
- `GET /v1/swarm/contracts` lists database-backed contract versions and the
  active version.
- `GET /v1/swarm/contract/diff?from_version=...&to_version=...` returns changed
  contract paths without treating the version label itself as a behavioral change.
- `POST /v1/swarm/contract` validates, saves, activates, and applies a swarm
  contract version for local configuration.
- `GET /v1/tasks` lists recent tasks for dashboards and local operators.
  Optional `status=waiting_approval` filters the list for approval queues.
- `POST /v1/tasks` creates a task.
- `GET /v1/tasks/{task_id}` returns task status.
- `GET /v1/tasks/{task_id}/events` returns public audit events. Optional
  `event_type`, `agent_id`, `trace_id`, `limit`, and `after_event_id` query
  parameters filter and page the task trace. Raw model reasoning payloads are
  not returned by default; the response exposes `raw_reasoning_refs` for
  sensitive audit lookup.
- `POST /v1/tasks/{task_id}/raw-reasoning/{event_id}/reveal` returns raw
  reasoning only when `acknowledge_sensitive=true` is provided.
- `GET /v1/tasks/{task_id}/stream` streams Server-Sent Events.
- `GET /v1/tasks/{task_id}/thinking-summary` returns public thinking summaries.
- `GET /v1/tasks/{task_id}/swarm-graph` returns graph-ready route events with
  route summary, node roles/counts, edge labels, selected status, and contract
  refs.
- `GET /v1/tasks/{task_id}/inspector` returns the current phase, agent states,
  and aggregate route/tool/error metrics derived from the public audit trace.
- `GET /v1/tasks/{task_id}/quality` returns evidence coverage, audit pass rate,
  correction counts, and read-only replay points from the audit trace.
- `GET /v1/tasks/{task_id}/checkpoints` returns safe event-backed checkpoint
  refs with phase, sequence, and resumable/terminal state.
- `GET /v1/tasks/{task_id}/budget` returns configured resource limits and
  admitted/rejected allocation decisions. Resource budget zero values preserve
  existing behavior and leave that resource unbounded.
- `POST /v1/tasks/{task_id}/research` creates an append-only research plan with
  a question, parameter catalog, hypotheses, deterministic why/how expansion,
  and unresolved questions; `GET /v1/tasks/{task_id}/research` retrieves the
  latest plan.
- `POST /v1/tasks/{task_id}/research/evidence` appends a validated evidence
  record linked to an optional hypothesis/parameter; `GET
  /v1/tasks/{task_id}/research/evidence` returns evidence count, confidence,
  hypothesis coverage, and unresolved questions.
- `POST /v1/tasks/{task_id}/research/influence` appends a weighted parameter
  influence (`-1..1`); `GET /v1/tasks/{task_id}/research/influence` returns
  sorted strong links and average absolute weight for the Observatory.
- `POST /v1/tasks/{task_id}/usage` appends resource usage records for an
  orchestrator, worker, or auditor; `GET /v1/tasks/{task_id}/usage` aggregates
  tokens, duration, estimated cost, branches, and role breakdown.
- `POST /v1/tasks/{task_id}/playbook/runs` records a replayable playbook run
  with version, status, quality score, and resource usage; `GET
  /v1/tasks/{task_id}/playbook/runs` compares runs by quality and cost.
- `POST /v1/tasks/{task_id}/playbook/template` records a versioned reusable
  template with stages, capabilities, and acceptance criteria; `GET
  /v1/playbooks/templates` lists the latest template per name.
- `POST /v1/tasks/{task_id}/memory` appends a validated structured memory note
  to the task trace; `GET /v1/tasks/{task_id}/memory?q=...` retrieves notes with
  deterministic token-overlap ranking by default. Set
  `MEMORY_RETRIEVAL_BACKEND=pgvector` with PostgreSQL to use the optional
  semantic index; the audit event remains the source of truth and lexical
  retrieval is the fallback.
- `GET /v1/memory/search?q=...` searches validated memory notes across task
  traces using the configured backend. `MEMORY_EMBEDDING_DIMENSIONS` defaults
  to 64 for the deterministic local embedding provider.
- `POST /v1/tasks/{task_id}/replay` creates a new task and trace from a valid
  event checkpoint, starts it in `waiting_approval`, and never mutates the
  source task history.
- `app/runtime/graph_adapter.py` is an optional, dependency-free LangGraph
  boundary: it translates TRIADA checkpoint refs into `thread_id` and
  `checkpoint_id` configuration without moving persistence ownership.
- Optional graph spike dependencies are available through `pip install -e '.[graph]'`.
  The isolated `app/runtime/langgraph_spike.py` demonstrates a checkpointed
  research subgraph; `run_research_subgraph` expands and audits a bounded plan
  using only supplied evidence refs. It is not wired into the TRIADA execution
  engine: the TRIADA event store remains the source of truth.
- `GET /v1/tasks/{task_id}/audit` verifies and returns the audit trace.
- `GET /v1/tasks/{task_id}/artifacts` returns artifact records.
- `POST /v1/tasks/{task_id}/approve`, `/cancel`, `/resume`, and `/run_once`
  control task execution.

Local dashboard:

- `GET /ui` opens a compact local TRIADA Swarm dashboard.
- The dashboard reads `/v1/llm/config`, `/v1/swarm/contract`,
  `/v1/tasks`, `/v1/tasks/{task_id}/events`,
  `/v1/tasks/{task_id}/swarm-graph`, and `/v1/tasks/{task_id}/thinking-summary`.
- It can save/test the active LLM provider, edit local swarm contracts through
  forms for chief auditor, scaling rules, and worker-auditor pairs, keep the
  raw JSON available for advanced changes, show contract routes, graph edges,
  a readable route list, task runs, audit events, public thinking summaries,
  raw reasoning refs with an explicit reveal checkbox, and a `waiting_approval`
  queue with approve actions. The selected task and event feed can auto-refresh
  while a run is active, and the event feed can load additional pages through
  the audit-event cursor. Raw reasoning stays in sensitive audit events and is
  hidden until explicitly revealed.

Safe read-only tools currently supported by the worker: `git status`, `echo`,
`pytest`, `rg`, `ls`, `cat`, and `sed` without mutating flags such as `-i`.

Example:

```bash
curl -sS -X POST http://127.0.0.1:8000/v1/tasks \
  -H 'content-type: application/json' \
  -d '{"goal":"inspect repository status","allowed_tools":["git"],"acceptance_criteria":["return status"]}'
```

## CLI

Run CLI commands through the module entrypoint:

```bash
python3 -m app.cli demo
python3 -m app.cli test-provider
python3 -m app.cli simulate-long-task
python3 -m app.cli run-task task.json
python3 -m app.cli list-events TRACE_UUID
python3 -m app.cli verify-trace TRACE_UUID
```

`run-task` accepts JSON with `goal` or `task` or `description`, plus optional
`allowed_tools` and `acceptance_criteria` lists.

## Validation Commands

```bash
python3 -m pytest tests/triada/test_docs.py -q
python3 -m pytest -q
python3 -m app.cli demo
python3 -m app.cli simulate-long-task
```
