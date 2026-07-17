# FixMost Handoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new `fixmost handoff` command that sends arbitrary prompts to the existing FixMost backend and returns either plain text or validated JSON, while keeping the current specialized commands working as wrappers over the shared execution path.

**Architecture:** Keep the shell entrypoint unchanged and refactor the Python code into a thin CLI layer plus two focused helper modules: one for FixMost transport and one for response extraction and JSON validation. Keep the codebase flat at the repository root, use `unittest` for tests, and route both `handoff` and the specialized commands through the same shared request path.

**Tech Stack:** Python 3 standard library (`argparse`, `json`, `os`, `sys`, `urllib`, `unittest`, `unittest.mock`, `tempfile`, `contextlib`, `io`)

---

## File Structure

Planned files and responsibilities:

- Modify: `fixmost_runner.py`
  - CLI parsing
  - input and system prompt source resolution
  - subcommand dispatch
  - shared execution path for `handoff` and wrappers
- Create: `fixmost_client.py`
  - FixMost API constants
  - HTTP request construction
  - API key validation
  - HTTP error translation
- Create: `fixmost_output.py`
  - response text extraction
  - strict JSON parsing for `--json`
- Modify: `README.md`
  - document `handoff`
  - update supported commands and examples
- Create: `tests/test_fixmost_output.py`
  - text extraction and strict JSON validation coverage
- Create: `tests/test_fixmost_client.py`
  - request payload and HTTP error handling coverage
- Create: `tests/test_fixmost_runner.py`
  - CLI source precedence
  - system prompt override precedence
  - `handoff` output modes
  - wrapper commands still using shared path

## Task 1: Add response extraction and JSON validation helpers

**Files:**
- Create: `fixmost_output.py`
- Test: `tests/test_fixmost_output.py`

- [ ] **Step 1: Write the failing tests for response text extraction and strict JSON mode**

```python
import json
import unittest

from fixmost_output import extract_json_text, extract_text


class ExtractTextTests(unittest.TestCase):
    def test_extract_text_from_string_content(self):
        payload = {"choices": [{"message": {"content": "hello"}}]}
        self.assertEqual(extract_text(payload), "hello")

    def test_extract_text_from_content_parts(self):
        payload = {
            "choices": [
                {
                    "message": {
                        "content": [
                            {"type": "text", "text": "alpha"},
                            {"type": "ignored", "text": "skip"},
                            "beta",
                        ]
                    }
                }
            ]
        }
        self.assertEqual(extract_text(payload), "alpha\nbeta")

    def test_extract_text_raises_when_choices_missing(self):
        with self.assertRaisesRegex(RuntimeError, "no choices"):
            extract_text({})

    def test_extract_text_raises_when_content_missing(self):
        payload = {"choices": [{"message": {"content": ""}}]}
        with self.assertRaisesRegex(RuntimeError, "empty content"):
            extract_text(payload)


class ExtractJsonTextTests(unittest.TestCase):
    def test_extract_json_text_returns_normalized_json(self):
        payload = {"choices": [{"message": {"content": '{\"b\":2,\"a\":1}'}}]}
        self.assertEqual(extract_json_text(payload), json.dumps({"a": 1, "b": 2}, indent=2, sort_keys=True))

    def test_extract_json_text_raises_for_invalid_json(self):
        payload = {"choices": [{"message": {"content": "not-json"}}]}
        with self.assertRaisesRegex(RuntimeError, "valid JSON"):
            extract_json_text(payload)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests/test_fixmost_output.py -v`
Expected: `FAILED` with `ModuleNotFoundError: No module named 'fixmost_output'`

- [ ] **Step 3: Write the minimal implementation**

```python
import json


def extract_text(payload):
    choices = payload.get("choices") or []
    if not choices:
        raise RuntimeError("FixMost returned no choices.")

    message = choices[0].get("message") or {}
    content = message.get("content")
    if not content:
        raise RuntimeError("FixMost returned empty content.")

    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
            elif isinstance(item, str):
                parts.append(item)
        text = "\n".join(part for part in parts if part)
        if text:
            return text

    if isinstance(content, str):
        return content

    return str(content)


def extract_json_text(payload):
    text = extract_text(payload)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("FixMost did not return valid JSON.") from exc
    return json.dumps(data, indent=2, sort_keys=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests/test_fixmost_output.py -v`
Expected: `OK`

- [ ] **Step 5: Record progress**

Because `/Users/hidanhidanov/fixmost_delegate` is currently not a git repository, do not add a commit step in this task. Instead, note completion in the task checklist and continue.

## Task 2: Add a focused FixMost transport module

**Files:**
- Create: `fixmost_client.py`
- Test: `tests/test_fixmost_client.py`

- [ ] **Step 1: Write the failing transport tests**

```python
import json
import unittest
from unittest import mock
from urllib import error

from fixmost_client import API_URL, MODEL, SYSTEM_PROMPT, call_fixmost


class CallFixMostTests(unittest.TestCase):
    @mock.patch.dict("os.environ", {}, clear=True)
    def test_call_fixmost_requires_api_key(self):
        with self.assertRaisesRegex(RuntimeError, "FIXMOST_API_KEY is not set"):
            call_fixmost("user prompt", SYSTEM_PROMPT)

    @mock.patch.dict("os.environ", {"FIXMOST_API_KEY": "secret"}, clear=True)
    @mock.patch("fixmost_client.request.urlopen")
    def test_call_fixmost_sends_expected_payload(self, mock_urlopen):
        response = mock.MagicMock()
        response.read.return_value = b'{"choices":[{"message":{"content":"ok"}}]}'
        mock_urlopen.return_value.__enter__.return_value = response

        payload = call_fixmost("user prompt", "system prompt")

        self.assertEqual(payload["choices"][0]["message"]["content"], "ok")
        args, kwargs = mock_urlopen.call_args
        http_request = args[0]
        body = json.loads(http_request.data.decode("utf-8"))

        self.assertEqual(http_request.full_url, API_URL)
        self.assertEqual(body["model"], MODEL)
        self.assertEqual(body["messages"][0], {"role": "system", "content": "system prompt"})
        self.assertEqual(body["messages"][1], {"role": "user", "content": "user prompt"})
        self.assertEqual(http_request.headers["Authorization"], "Bearer secret")
        self.assertEqual(kwargs["timeout"], 120)

    @mock.patch.dict("os.environ", {"FIXMOST_API_KEY": "secret"}, clear=True)
    @mock.patch("fixmost_client.request.urlopen")
    def test_call_fixmost_wraps_http_error(self, mock_urlopen):
        http_error = error.HTTPError(
            API_URL,
            400,
            "Bad Request",
            hdrs=None,
            fp=mock.Mock(read=mock.Mock(return_value=b'{"error":"bad"}')),
        )
        mock_urlopen.side_effect = http_error

        with self.assertRaisesRegex(RuntimeError, "FixMost HTTP 400"):
            call_fixmost("user prompt", SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests/test_fixmost_client.py -v`
Expected: `FAILED` with `ModuleNotFoundError: No module named 'fixmost_client'`

- [ ] **Step 3: Write the minimal implementation**

```python
import json
import os
from urllib import error, request


API_URL = "https://api.llm.fixmost.com/v1/public/chat/completions"
MODEL = "corp-coder"
SYSTEM_PROMPT = (
    "You are a concise code analysis assistant. "
    "Never assume access to secrets. "
    "Never ask for secrets. "
    "Focus on structure, behavior, risk, and next checks."
)


def call_fixmost(prompt, system_prompt):
    api_key = os.environ.get("FIXMOST_API_KEY")
    if not api_key:
        raise RuntimeError("FIXMOST_API_KEY is not set.")

    payload = json.dumps(
        {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
        }
    ).encode("utf-8")

    http_request = request.Request(
        API_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with request.urlopen(http_request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"FixMost HTTP {exc.code}: {body[:1000]}") from exc
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests/test_fixmost_client.py -v`
Expected: `OK`

- [ ] **Step 5: Record progress**

Because the workspace is not a git repository, skip commit creation and continue with the next task.

## Task 3: Refactor the CLI around `handoff` and shared prompt execution

**Files:**
- Modify: `fixmost_runner.py`
- Test: `tests/test_fixmost_runner.py`

- [ ] **Step 1: Write the failing CLI tests**

```python
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

import fixmost_runner


class MainTests(unittest.TestCase):
    def run_main(self, argv, stdin_text=""):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.object(fixmost_runner.sys, "argv", ["fixmost"] + argv):
            with mock.patch("sys.stdin", io.StringIO(stdin_text)):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    try:
                        fixmost_runner.main()
                        exit_code = 0
                    except SystemExit as exc:
                        exit_code = exc.code if isinstance(exc.code, int) else 1
        return exit_code, stdout.getvalue(), stderr.getvalue()

    @mock.patch("fixmost_runner.call_fixmost")
    def test_handoff_reads_prompt_argument_and_prints_text(self, mock_call_fixmost):
        mock_call_fixmost.return_value = {"choices": [{"message": {"content": "done"}}]}
        exit_code, stdout, stderr = self.run_main(["handoff", "--prompt", "hello"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.strip(), "done")
        self.assertEqual(stderr, "")
        mock_call_fixmost.assert_called_once_with("hello", fixmost_runner.DEFAULT_SYSTEM_PROMPT)

    @mock.patch("fixmost_runner.call_fixmost")
    def test_handoff_reads_input_file(self, mock_call_fixmost):
        mock_call_fixmost.return_value = {"choices": [{"message": {"content": "done"}}]}
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=False) as fh:
            fh.write("from-file")
            path = fh.name
        try:
            exit_code, stdout, _ = self.run_main(["handoff", "--input-file", path])
        finally:
            os.unlink(path)
        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.strip(), "done")
        mock_call_fixmost.assert_called_once_with("from-file", fixmost_runner.DEFAULT_SYSTEM_PROMPT)

    @mock.patch("fixmost_runner.call_fixmost")
    def test_handoff_reads_stdin_when_no_flags_are_given(self, mock_call_fixmost):
        mock_call_fixmost.return_value = {"choices": [{"message": {"content": "done"}}]}
        exit_code, stdout, _ = self.run_main(["handoff"], stdin_text="from-stdin")
        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.strip(), "done")
        mock_call_fixmost.assert_called_once_with("from-stdin", fixmost_runner.DEFAULT_SYSTEM_PROMPT)

    def test_handoff_rejects_prompt_and_input_file_together(self):
        exit_code, _, stderr = self.run_main(["handoff", "--prompt", "x", "--input-file", "/tmp/x"])
        self.assertEqual(exit_code, 2)
        self.assertIn("not allowed with argument", stderr)

    @mock.patch("fixmost_runner.call_fixmost")
    def test_handoff_uses_system_override_argument(self, mock_call_fixmost):
        mock_call_fixmost.return_value = {"choices": [{"message": {"content": "done"}}]}
        exit_code, _, _ = self.run_main(["handoff", "--prompt", "hello", "--system", "be strict"])
        self.assertEqual(exit_code, 0)
        mock_call_fixmost.assert_called_once_with("hello", "be strict")

    @mock.patch("fixmost_runner.call_fixmost")
    def test_handoff_uses_system_file_when_system_argument_is_missing(self, mock_call_fixmost):
        mock_call_fixmost.return_value = {"choices": [{"message": {"content": "done"}}]}
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=False) as fh:
            fh.write("system-file")
            path = fh.name
        try:
            exit_code, _, _ = self.run_main(["handoff", "--prompt", "hello", "--system-file", path])
        finally:
            os.unlink(path)
        self.assertEqual(exit_code, 0)
        mock_call_fixmost.assert_called_once_with("hello", "system-file")

    @mock.patch("fixmost_runner.call_fixmost")
    def test_handoff_prints_normalized_json_in_json_mode(self, mock_call_fixmost):
        mock_call_fixmost.return_value = {"choices": [{"message": {"content": '{"z":1,"a":2}'}}]}
        exit_code, stdout, _ = self.run_main(["handoff", "--prompt", "hello", "--json"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(stdout), {"a": 2, "z": 1})

    @mock.patch("fixmost_runner.call_fixmost")
    def test_handoff_returns_error_for_invalid_json_mode(self, mock_call_fixmost):
        mock_call_fixmost.return_value = {"choices": [{"message": {"content": "oops"}}]}
        exit_code, _, stderr = self.run_main(["handoff", "--prompt", "hello", "--json"])
        self.assertEqual(exit_code, 1)
        self.assertIn("valid JSON", stderr)

    @mock.patch("fixmost_runner.call_fixmost")
    def test_specialized_command_uses_shared_execution_path(self, mock_call_fixmost):
        mock_call_fixmost.return_value = {"choices": [{"message": {"content": "summary"}}]}
        exit_code, stdout, _ = self.run_main(["summarize-file"], stdin_text="payload")
        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.strip(), "summary")
        called_prompt = mock_call_fixmost.call_args.args[0]
        self.assertIn("Summarize this source file", called_prompt)
        self.assertIn("INPUT:\npayload", called_prompt)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests/test_fixmost_runner.py -v`
Expected: `FAILED` because `fixmost_runner` does not yet define the new CLI shape and helper constants

- [ ] **Step 3: Rewrite the CLI entrypoint around subcommands and shared execution**

```python
import argparse
import sys

from fixmost_client import SYSTEM_PROMPT as DEFAULT_SYSTEM_PROMPT
from fixmost_client import call_fixmost
from fixmost_output import extract_json_text, extract_text


SPECIALIZED_INSTRUCTIONS = {
    "summarize-file": (
        "Summarize this source file. "
        "Return responsibilities, key functions, main dependencies, and risks."
    ),
    "summarize-diff": (
        "Summarize this diff. "
        "Return intent, behavior changes, risk areas, and validation suggestions."
    ),
    "extract-endpoints": (
        "Extract all endpoints, methods, auth patterns, and payload shapes. "
        "Group similar routes when useful."
    ),
    "analyze-logs": (
        "Summarize these logs. "
        "Return the likely issue, evidence, and next checks."
    ),
}


def read_text_file(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def resolve_prompt(args):
    if getattr(args, "prompt", None) is not None:
        return args.prompt
    if getattr(args, "input_file", None):
        return read_text_file(args.input_file)
    return sys.stdin.read()


def resolve_system_prompt(args):
    if getattr(args, "system", None) is not None:
        return args.system
    if getattr(args, "system_file", None):
        return read_text_file(args.system_file)
    return DEFAULT_SYSTEM_PROMPT


def build_specialized_prompt(mode, payload):
    return f"{SPECIALIZED_INSTRUCTIONS[mode]}\n\nINPUT:\n{payload}"


def run_prompt(prompt, system_prompt, json_mode=False):
    payload = call_fixmost(prompt, system_prompt)
    if json_mode:
        return extract_json_text(payload)
    return extract_text(payload)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Delegate low-risk analytical tasks to FixMost / corp-coder."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    handoff_parser = subparsers.add_parser("handoff")
    prompt_group = handoff_parser.add_mutually_exclusive_group()
    prompt_group.add_argument("--prompt")
    prompt_group.add_argument("--input-file")
    handoff_parser.add_argument("--json", action="store_true")
    handoff_parser.add_argument("--system")
    handoff_parser.add_argument("--system-file")

    for command in SPECIALIZED_INSTRUCTIONS:
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("--input-file")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "handoff":
        prompt = resolve_prompt(args)
        system_prompt = resolve_system_prompt(args)
        print(run_prompt(prompt, system_prompt, json_mode=args.json))
        return

    payload = resolve_prompt(args)
    prompt = build_specialized_prompt(args.command, payload)
    print(run_prompt(prompt, DEFAULT_SYSTEM_PROMPT, json_mode=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
```

- [ ] **Step 4: Run the CLI tests to verify they pass**

Run: `python3 -m unittest tests/test_fixmost_runner.py -v`
Expected: `OK`

- [ ] **Step 5: Run the combined test suite**

Run: `python3 -m unittest discover -s tests -v`
Expected: `OK`

## Task 4: Document `handoff` and preserve wrapper behavior in user-facing docs

**Files:**
- Modify: `README.md`
- Test: `tests/test_fixmost_runner.py`

- [ ] **Step 1: Extend the existing CLI test with wrapper coverage if it is still missing**

```python
    @mock.patch("fixmost_runner.call_fixmost")
    def test_specialized_command_reads_input_file(self, mock_call_fixmost):
        mock_call_fixmost.return_value = {"choices": [{"message": {"content": "summary"}}]}
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=False) as fh:
            fh.write("payload-from-file")
            path = fh.name
        try:
            exit_code, stdout, _ = self.run_main(["summarize-diff", "--input-file", path])
        finally:
            os.unlink(path)
        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.strip(), "summary")
        called_prompt = mock_call_fixmost.call_args.args[0]
        self.assertIn("Summarize this diff", called_prompt)
        self.assertIn("INPUT:\npayload-from-file", called_prompt)
```

- [ ] **Step 2: Run the targeted CLI test**

Run: `python3 -m unittest tests/test_fixmost_runner.py -v`
Expected: `OK`

- [ ] **Step 3: Update the README examples and supported command list**

```markdown
# FixMost Delegate Toolkit

External toolkit for delegating low-risk analytical tasks to `FixMost / corp-coder`.

This toolkit is intentionally independent from any конкретный repository. It lives at:

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
```

- [ ] **Step 4: Run the full test suite again after the documentation-adjacent wrapper check**

Run: `python3 -m unittest discover -s tests -v`
Expected: `OK`

- [ ] **Step 5: Record progress**

Because the workspace is not a git repository, finish by marking the task complete in the plan rather than creating a commit.

## Self-Review

Spec coverage check:

- `fixmost handoff` exists as the new CLI primitive: covered by Task 3
- plain text default output: covered by Task 3 tests and implementation
- strict `--json` mode: covered by Tasks 1 and 3
- hybrid system prompt override: covered by Task 3
- existing specialized commands remain as wrappers: covered by Tasks 3 and 4
- documentation update: covered by Task 4

Placeholder scan:

- no `TODO`, `TBD`, or deferred implementation placeholders remain
- all planned code changes have exact file paths and concrete code blocks

Type consistency:

- the plan uses `call_fixmost(prompt, system_prompt)` consistently
- the default system prompt constant is exposed as `DEFAULT_SYSTEM_PROMPT` in the CLI and sourced from `fixmost_client.SYSTEM_PROMPT`
- strict JSON mode consistently returns normalized JSON text from `extract_json_text`
