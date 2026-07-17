# FixMost Delegate Toolkit

External toolkit for delegating low-risk analytical tasks to `FixMost / corp-coder`.

This toolkit is intentionally independent from any specific repository. It lives at:

- `/Users/hidanhidanov/fixmost_delegate/`

## What It Does

- delegates arbitrary prompts through `fixmost handoff`
- summarizes large source files
- summarizes diffs
- extracts endpoint maps
- analyzes sanitized logs

## What It Does Not Do

- does not edit your repository
- does not read project config automatically
- does not depend on `authomation`
- does not manage secrets

## Requirements

- `python3`
- `FIXMOST_API_KEY` in the environment

## Supported Commands

- `handoff`
- `summarize-file`
- `summarize-diff`
- `extract-endpoints`
- `analyze-logs`

## Example Usage

Run from any directory by absolute path:

```bash
/Users/hidanhidanov/fixmost_delegate/fixmost handoff --prompt "Summarize the responsibilities of this module"
cat /absolute/path/to/prompt.txt | /Users/hidanhidanov/fixmost_delegate/fixmost handoff
/Users/hidanhidanov/fixmost_delegate/fixmost handoff --prompt "Return JSON with keys summary and risks" --json
/Users/hidanhidanov/fixmost_delegate/fixmost handoff --prompt "Review this code like a strict API auditor" --system "You are a strict API auditor."
/Users/hidanhidanov/fixmost_delegate/fixmost summarize-file --input-file /absolute/path/to/file.py
git diff | /Users/hidanhidanov/fixmost_delegate/fixmost summarize-diff
/Users/hidanhidanov/fixmost_delegate/fixmost extract-endpoints --input-file /absolute/path/to/app.py
cat /absolute/path/to/sanitized.log | /Users/hidanhidanov/fixmost_delegate/fixmost analyze-logs
```

## Safety Rules

Never send:

- passwords
- tokens
- cookies
- Vault secrets
- service account JSON

Allowed examples:

- large safe source files
- diffs
- endpoint maps
- sanitized logs
- structural summaries
- arbitrary non-secret prompts for Codex handoff
