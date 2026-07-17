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
        self.assertEqual(
            body["messages"][0], {"role": "system", "content": "system prompt"}
        )
        self.assertEqual(
            body["messages"][1], {"role": "user", "content": "user prompt"}
        )
        self.assertEqual(http_request.headers["Authorization"], "Bearer secret")
        self.assertEqual(http_request.headers["Content-type"], "application/json")
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
