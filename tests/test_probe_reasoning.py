import unittest
from unittest import mock

import probe_reasoning


class MakeCasesTests(unittest.TestCase):
    def test_make_cases_includes_nested_thinking_variants_for_both_stream_modes(self):
        case_names = {name for name, _ in probe_reasoning.make_cases()}

        self.assertIn(
            "chat_template_kwargs_enable_thinking_true__stream_false", case_names
        )
        self.assertIn(
            "chat_template_kwargs_enable_thinking_true__stream_true", case_names
        )
        self.assertIn(
            "extra_body_chat_template_kwargs_enable_thinking_true__stream_false",
            case_names,
        )
        self.assertIn(
            "extra_body_chat_template_kwargs_enable_thinking_true__stream_true",
            case_names,
        )
        self.assertIn(
            "extraBody_chat_template_kwargs_enable_thinking_true__stream_false",
            case_names,
        )
        self.assertIn(
            "extraBody_chat_template_kwargs_enable_thinking_true__stream_true",
            case_names,
        )


class StreamAnalysisTests(unittest.TestCase):
    def test_analyze_response_collects_stream_delta_keys_and_reasoning_paths(self):
        raw_text = "\n".join(
            [
                'data: {"choices":[{"delta":{"role":"assistant"}}]}',
                'data: {"choices":[{"delta":{"content":"hello","reasoning_content":"hidden"}}]}',
                "data: [DONE]",
            ]
        )

        analysis = probe_reasoning.analyze_response(raw_text, None)

        self.assertEqual(analysis["stream_delta_keys"], ["content", "reasoning_content", "role"])
        self.assertIn("$[1].choices[0].delta.reasoning_content", analysis["found_key_paths"])


class ReportRenderingTests(unittest.TestCase):
    def test_render_markdown_report_mentions_model_hints_and_case_findings(self):
        meta = {
            "api_url": "https://api.llm.fixmost.com/v1/public/chat/completions",
            "model": "corp-coder",
        }
        summary = [
            {
                "case": "baseline__stream_false",
                "ok": True,
                "status": 200,
                "json_parsed": True,
                "found_key_paths": [],
                "has_think_tags": False,
                "stream_delta_keys": [],
                "preview": "plain answer",
            },
            {
                "case": "thinking_true__stream_true",
                "ok": True,
                "status": 200,
                "json_parsed": False,
                "found_key_paths": ["$[1].choices[0].delta.reasoning_content"],
                "has_think_tags": False,
                "stream_delta_keys": ["content", "reasoning_content", "role"],
                "preview": "stream answer",
            },
        ]
        models_payload = {
            "data": [
                {
                    "id": "corp-coder",
                    "description": "Supports thinking and tool-calling",
                    "capabilities": {"thinking": True},
                }
            ]
        }

        report = probe_reasoning.render_markdown_report(meta, summary, models_payload)

        self.assertIn("# Reasoning Probe Report", report)
        self.assertIn("corp-coder", report)
        self.assertIn("Supports thinking and tool-calling", report)
        self.assertIn("thinking_true__stream_true", report)
        self.assertIn("reasoning_content", report)


class CallApiTests(unittest.TestCase):
    @mock.patch("probe_reasoning.request.urlopen")
    def test_call_api_handles_get_without_payload(self, mock_urlopen):
        response = mock.MagicMock()
        response.read.return_value = b'{"data":[{"id":"corp-coder"}]}'
        response.headers.items.return_value = [("Content-Type", "application/json")]
        response.status = 200
        mock_urlopen.return_value.__enter__.return_value = response

        result = probe_reasoning.call_api(
            None,
            "secret",
            url=probe_reasoning.MODELS_URL,
            method="GET",
        )

        self.assertTrue(result["ok"])
        args, kwargs = mock_urlopen.call_args
        http_request = args[0]
        self.assertEqual(http_request.method, "GET")
        self.assertIsNone(http_request.data)
        self.assertEqual(kwargs["timeout"], 180)


if __name__ == "__main__":
    unittest.main()
