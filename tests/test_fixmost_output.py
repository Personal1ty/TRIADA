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
        payload = {"choices": [{"message": {"content": '{"b":2,"a":1}'}}]}
        self.assertEqual(
            extract_json_text(payload),
            json.dumps({"a": 1, "b": 2}, indent=2, sort_keys=True),
        )

    def test_extract_json_text_raises_for_invalid_json(self):
        payload = {"choices": [{"message": {"content": "not-json"}}]}
        with self.assertRaisesRegex(RuntimeError, "valid JSON"):
            extract_json_text(payload)


if __name__ == "__main__":
    unittest.main()
