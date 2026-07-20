# Agent Instructions

These instructions apply to future agents working in this repository.

## Project Rules

- Keep TRIADA role boundaries explicit: Orchestrator plans, Worker executes,
  Auditor verifies.
- Use `python3`, not `python`, in commands and documentation.
- Prefer deterministic tests with `FakeLLMProvider` and `FakeClock`.
- Treat raw model reasoning as sensitive audit data. Public progress should use
  `thinking_summary_delta` records.
- Redact secrets before writing audit events, logs, or artifacts.
- Treat audit events as append-only; add new events instead of mutating history.

## Development Workflow

- Add or update tests before implementation changes.
- Keep patches scoped to the requested files and behavior.
- Run focused tests first, then `python3 -m pytest -q`.
- Document new environment variables in `.env.example`.
- For API changes, update README endpoint docs and event examples when relevant.

## Operational Safety

- Apply `risk_policy` consistently for every tool request.
- Require approvals for high-risk and destructive actions.
- Include validation commands for low-risk writes.
- Store large command output as artifacts or refs when possible.
