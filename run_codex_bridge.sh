#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

export LLM_PROVIDER="${LLM_PROVIDER:-codex-bridge}"
export DATABASE_URL="${DATABASE_URL:-sqlite+aiosqlite:///./triada.db}"

exec uvicorn app.main:create_app --factory --host "${TRIADA_HOST:-127.0.0.1}" --port "${TRIADA_PORT:-8000}"
