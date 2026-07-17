import io
import json
import os
import tempfile
import unittest
import warnings
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

import fixmost_runner


class MainTests(unittest.TestCase):
    def run_main(self, argv, stdin_text=""):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.object(fixmost_runner.sys, "argv", ["fixmost"] + argv):
            with mock.patch("sys.stdin", io.StringIO(stdin_text)):
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", ResourceWarning)
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
        mock_call_fixmost.assert_called_once_with(
            "hello", fixmost_runner.DEFAULT_SYSTEM_PROMPT
        )

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
        mock_call_fixmost.assert_called_once_with(
            "from-file", fixmost_runner.DEFAULT_SYSTEM_PROMPT
        )

    @mock.patch("fixmost_runner.call_fixmost")
    def test_handoff_reads_stdin_when_no_flags_are_given(self, mock_call_fixmost):
        mock_call_fixmost.return_value = {"choices": [{"message": {"content": "done"}}]}

        exit_code, stdout, _ = self.run_main(["handoff"], stdin_text="from-stdin")

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.strip(), "done")
        mock_call_fixmost.assert_called_once_with(
            "from-stdin", fixmost_runner.DEFAULT_SYSTEM_PROMPT
        )

    def test_handoff_rejects_prompt_and_input_file_together(self):
        exit_code, _, stderr = self.run_main(
            ["handoff", "--prompt", "x", "--input-file", "/tmp/x"]
        )

        self.assertEqual(exit_code, 2)
        self.assertIn("not allowed with argument", stderr)

    @mock.patch("fixmost_runner.call_fixmost")
    def test_handoff_uses_system_override_argument(self, mock_call_fixmost):
        mock_call_fixmost.return_value = {"choices": [{"message": {"content": "done"}}]}

        exit_code, _, _ = self.run_main(
            ["handoff", "--prompt", "hello", "--system", "be strict"]
        )

        self.assertEqual(exit_code, 0)
        mock_call_fixmost.assert_called_once_with("hello", "be strict")

    @mock.patch("fixmost_runner.call_fixmost")
    def test_handoff_uses_system_file_when_system_argument_is_missing(
        self, mock_call_fixmost
    ):
        mock_call_fixmost.return_value = {"choices": [{"message": {"content": "done"}}]}
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=False) as fh:
            fh.write("system-file")
            path = fh.name
        try:
            exit_code, _, _ = self.run_main(
                ["handoff", "--prompt", "hello", "--system-file", path]
            )
        finally:
            os.unlink(path)

        self.assertEqual(exit_code, 0)
        mock_call_fixmost.assert_called_once_with("hello", "system-file")

    @mock.patch("fixmost_runner.call_fixmost")
    def test_handoff_prefers_system_argument_over_system_file(
        self, mock_call_fixmost
    ):
        mock_call_fixmost.return_value = {"choices": [{"message": {"content": "done"}}]}
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=False) as fh:
            fh.write("system-file")
            path = fh.name
        try:
            exit_code, _, _ = self.run_main(
                [
                    "handoff",
                    "--prompt",
                    "hello",
                    "--system",
                    "be strict",
                    "--system-file",
                    path,
                ]
            )
        finally:
            os.unlink(path)

        self.assertEqual(exit_code, 0)
        mock_call_fixmost.assert_called_once_with("hello", "be strict")

    @mock.patch("fixmost_runner.call_fixmost")
    def test_handoff_prints_normalized_json_in_json_mode(self, mock_call_fixmost):
        mock_call_fixmost.return_value = {
            "choices": [{"message": {"content": '{"z":1,"a":2}'}}]
        }

        exit_code, stdout, _ = self.run_main(["handoff", "--prompt", "hello", "--json"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            stdout.strip(), json.dumps({"a": 2, "z": 1}, indent=2, sort_keys=True)
        )

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
        self.assertEqual(
            mock_call_fixmost.call_args.args[1], fixmost_runner.DEFAULT_SYSTEM_PROMPT
        )

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


if __name__ == "__main__":
    unittest.main()
