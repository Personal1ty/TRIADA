# DevOps Tools

TRIADA executes external actions through adapter contracts rather than direct
unbounded shell access.

## Adapter Contract

Each adapter implements `ToolAdapter`:

- `validate_input(request)`: reject unsupported commands, paths, or risk.
- `dry_run(request)`: describe intended work when possible.
- `execute(request)`: run the command and return a `ToolResult`.
- `validate_result(result)`: enforce adapter-specific success rules.
- `rollback(request, result)`: undo the change when supported.

`ToolRequest` includes `command`, `working_dir`, `risk_policy`, `approval_ref`,
`expected_change`, `validation_command`, and `rollback_action`.

`ToolResult` records `tool`, `command`, `exit_code`, redacted `stdout` and
`stderr`, timeout state, timestamps, and metadata.

## Safe Command Matrix

| Risk policy | Examples | Required controls |
| --- | --- | --- |
| `read_only` | `git status`, `python3 -m pytest -q`, `kubectl get pods` | Valid command and bounded output |
| `low_risk_write` | format files, write generated docs, update config in workspace | `expected_change` and `validation_command` |
| `high_risk_write` | deploy, mutate remote state, alter infrastructure | explicit `approval_ref` |
| `destructive` | delete data, drop resources, reset state | explicit `approval_ref` and rollback plan when possible |

## Current Adapter Areas

The repository contains adapter modules for shell, filesystem, git, docker,
kubernetes, and terraform. Each adapter must enforce the base risk policy before
execution and should redact or reference large outputs rather than embedding
secrets in audit payloads.
