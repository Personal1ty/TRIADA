# TRIADA

TRIADA is an auditable DevOps task runner MVP built around three roles:
Orchestrator, Worker, and Auditor. The current codebase exposes a FastAPI API,
a small CLI, append-only audit events, redaction, safe tool adapter contracts,
and deterministic fake LLM behavior for local development.

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
The default non-Docker setting is `sqlite+aiosqlite:///./triada.db`.

## Install

Runtime dependencies are declared in `pyproject.toml`. Test dependencies are in
the `test` extra.

```bash
python3 -m pip install -e .
python3 -m pip install -e '.[test]'
```

Copy `.env.example` to `.env` to override settings. The fake provider is the
default and does not require an API key.

## API

The FastAPI application factory is `app.main:create_app`.

Core endpoints under `/v1`:

- `POST /v1/tasks` creates a task.
- `GET /v1/tasks/{task_id}` returns task status.
- `GET /v1/tasks/{task_id}/events` returns redacted audit events.
- `GET /v1/tasks/{task_id}/stream` streams Server-Sent Events.
- `GET /v1/tasks/{task_id}/thinking-summary` returns public thinking summaries.
- `GET /v1/tasks/{task_id}/audit` verifies and returns the audit trace.
- `GET /v1/tasks/{task_id}/artifacts` returns artifact records.
- `POST /v1/tasks/{task_id}/approve`, `/cancel`, `/resume`, and `/run_once`
  control task execution.

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
