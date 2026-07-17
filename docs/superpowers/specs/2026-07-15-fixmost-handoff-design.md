# FixMost Handoff Design

## Goal

Turn this toolkit into a CLI-first handoff runner that lets Codex delegate arbitrary prompt execution to the FixMost backend and receive either plain text or validated JSON back.

## Context

The current toolkit already has:

- a shell entrypoint at `fixmost`
- a Python runner at `fixmost_runner.py`
- four task-specific modes:
  - `summarize-file`
  - `summarize-diff`
  - `extract-endpoints`
  - `analyze-logs`

The current implementation is tied to one backend:

- API URL: `https://api.llm.fixmost.com/v1/public/chat/completions`
- model: `corp-coder`

The current problem is that the toolkit can only run fixed prompt templates. Codex needs a general-purpose handoff primitive so it can offload low-cost analysis, save tokens, and reduce its own active context.

## Chosen Approach

Use a CLI-first design with a new `fixmost handoff` command while keeping the current specialized commands as wrappers.

This provides:

- a stable `prompt in -> result out` contract for Codex
- minimal integration complexity
- easy shell composition with stdin/stdout
- future backend flexibility without changing the external command shape

## Alternatives Considered

### A. Minimal patch in the existing file

Add `handoff` directly into the current file with minimal restructuring.

Why rejected:

- keeps transport, CLI, and response parsing mixed together
- makes `--json` and system prompt override less clean
- creates friction for future extension

### B. Small normalization

Keep the toolkit small but split responsibilities into CLI parsing, FixMost transport, and response extraction/validation.

Why chosen:

- enough structure for the new handoff use case
- no premature adapter abstraction
- small code surface and low risk

### C. Full adapter architecture now

Build a backend abstraction immediately, even though only FixMost is implemented.

Why rejected for now:

- adds abstraction before it is needed
- increases complexity without immediate benefit

## CLI Contract

The new command is:

```bash
fixmost handoff
```

Supported input methods:

- `fixmost handoff --prompt "Summarize this module"`
- `fixmost handoff --input-file /tmp/prompt.txt`
- `cat prompt.txt | fixmost handoff`

Input precedence:

1. `--prompt`
2. `--input-file`
3. `stdin`

If mutually exclusive prompt sources are provided together, CLI validation should fail.

## Output Contract

Default mode:

- print plain text to `stdout`

JSON mode:

- enabled with `--json`
- extract model text
- parse it as JSON
- print normalized JSON to `stdout`
- if parsing fails, print an error to `stderr` and exit with code `1`

This makes the command usable both for human-readable delegation and structured Codex workflows.

## System Prompt Contract

Use a hybrid strategy:

- built-in safe default system prompt
- optional override through `--system`
- optional override through `--system-file`

Precedence:

1. `--system`
2. `--system-file`
3. built-in default

This keeps the tool safe by default while still allowing task-specific behavior from Codex.

## Backend Scope

First version supports only the existing FixMost backend.

No backend selection flag is needed yet. The toolkit remains intentionally bound to:

- FixMost API URL
- `corp-coder` model

The external interface should still be generic enough that another backend can be introduced later without changing the `fixmost handoff` command shape.

## Internal Structure

Refactor the toolkit into three responsibility areas:

### 1. CLI entrypoint

Responsible for:

- subcommand parsing
- argument validation
- input loading
- output mode selection

### 2. FixMost transport

Responsible for:

- building request payloads
- sending `messages` to the FixMost API
- handling HTTP errors
- returning decoded response payloads

### 3. Response extraction and validation

Responsible for:

- extracting text from the model response
- validating and formatting JSON mode output
- surfacing empty or malformed response errors

The existing specialized commands should be implemented as prompt builders that call the same shared handoff path.

## Specialized Commands

Keep the existing commands:

- `summarize-file`
- `summarize-diff`
- `extract-endpoints`
- `analyze-logs`

They should remain available because they are convenient wrappers for recurring tasks. Internally, they should:

- construct their task-specific prompt
- call the same shared FixMost execution path
- print the resulting text

This preserves backward compatibility while making `handoff` the primary primitive for Codex usage.

## Error Handling

Behavior to preserve explicitly:

- missing `FIXMOST_API_KEY`: print clear error to `stderr`, exit `1`
- invalid CLI combination such as `--prompt` with `--input-file`: validation error, exit `2`
- backend response has no choices or no content: print clear error to `stderr`, exit `1`
- `--json` response is not valid JSON: print clear error to `stderr`, exit `1`

No retries are required in the first version.

## Non-Goals

This toolkit does not:

- edit repository files
- apply diffs automatically
- manage memory or session history
- act as an autonomous agent
- do tool calling
- manage secrets beyond reading `FIXMOST_API_KEY` from the environment

Its role is narrow and deliberate: external inference runner for Codex.

## Testing Strategy

Testing should cover:

- input source precedence
- CLI validation for conflicting prompt inputs
- system prompt override precedence
- plain text extraction
- JSON validation success and failure paths
- handling of empty backend responses
- specialized commands still working through the shared path

Network calls should be isolated behind the transport layer so tests can stub the backend response cleanly.

## Success Criteria

The design is successful when:

- Codex can call `fixmost handoff` with an arbitrary prompt
- the toolkit returns plain text by default
- the toolkit can enforce valid JSON output with `--json`
- the existing specialized commands still work
- the implementation remains small and easy to extend later
