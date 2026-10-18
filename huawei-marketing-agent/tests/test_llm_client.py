"""Offline HTTP substitutes for the JSON-only LLM client."""

import io
import json
import os
import socket
import unittest
from urllib.error import HTTPError, URLError
from urllib.request import Request
from unittest.mock import patch

from src.llm_client import LLMClient, LLMClientError, _NoRedirect


def chat(content):
    return {"choices": [{"message": {"content": content}}]}


def responses(content):
    return {"output": [{"type": "message", "content": [{"type": "output_text", "text": content}]}]}


class FakeOpener:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, bytes):
            return io.BytesIO(item)
        return io.BytesIO(json.dumps(item, ensure_ascii=False).encode("utf-8"))


class LLMClientTests(unittest.TestCase):
    def make_client(self, opener, **kwargs):
        configured = {
            "api_key": "offline-placeholder",
            "base_url": "https://example.invalid/v1",
            "model": "offline-model",
        }
        configured.update(kwargs)
        with patch("src.llm_client.build_opener", return_value=opener):
            return LLMClient(**configured)

    def test_chat_json_unicode_payload_and_format(self):
        opener = FakeOpener(chat('{"title":"开学季"}'))
        client = self.make_client(opener, timeout=12)
        self.assertEqual(client.generate_json("只按证据生成", {"型号": "华为 PC"}), {"title": "开学季"})
        request, timeout = opener.calls[0]
        body = json.loads(request.data)
        self.assertEqual(request.full_url, "https://example.invalid/v1/chat/completions")
        self.assertEqual(timeout, 12)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer offline-placeholder")
        self.assertEqual(request.get_header("User-agent"), "huawei-marketing-agent/0.4")
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertIn("华为 PC", body["messages"][1]["content"])
        self.assertNotIn(b"\\u534e", request.data)
        self.assertEqual(client.api_type, "chat_completions")

    def test_responses_json_output_and_format(self):
        opener = FakeOpener(responses('{"title":"真实证据"}'))
        client = self.make_client(opener, api_type="responses")
        self.assertEqual(client.generate_json("system", {"evidence": []}), {"title": "真实证据"})
        request, _ = opener.calls[0]
        body = json.loads(request.data)
        self.assertEqual(request.full_url, "https://example.invalid/v1/responses")
        self.assertEqual(body["text"], {"format": {"type": "json_object"}})
        self.assertIn("JSON", body["instructions"])
        self.assertEqual(json.loads(body["input"]), {"evidence": []})
        self.assertNotIn("messages", body)

    def test_endpoint_normalization_adds_v1_only_once(self):
        for base in (
            "https://example.invalid",
            "https://example.invalid/",
            "https://example.invalid/v1/",
            "https://example.invalid/v1/chat/completions",
        ):
            with self.subTest(base=base):
                opener = FakeOpener(chat("{}"))
                self.make_client(opener, base_url=base).generate_json("system", {})
                self.assertEqual(opener.calls[0][0].full_url, "https://example.invalid/v1/chat/completions")
        opener = FakeOpener(responses("{}"))
        self.make_client(opener, base_url="https://example.invalid/proxy/v1", api_type="responses").generate_json("system", {})
        self.assertEqual(opener.calls[0][0].full_url, "https://example.invalid/proxy/v1/responses")

    def test_removes_json_code_fence_without_retry(self):
        opener = FakeOpener(chat('```json\n{"ok":true}\n```'))
        self.assertEqual(self.make_client(opener).generate_json("system", {}), {"ok": True})
        self.assertEqual(len(opener.calls), 1)

    def test_invalid_generated_json_retries_once_then_succeeds(self):
        opener = FakeOpener(chat("invalid output"), chat('{"ok":true}'))
        self.assertEqual(self.make_client(opener).generate_json("system", {}), {"ok": True})
        self.assertEqual(len(opener.calls), 2)
        retry = json.loads(opener.calls[1][0].data)
        self.assertIn("without Markdown fences", retry["messages"][0]["content"])

    def test_invalid_json_retries_at_most_once_and_never_exposes_raw_text(self):
        opener = FakeOpener(chat("secret-response"), chat("secret-response"))
        with self.assertRaises(LLMClientError) as raised:
            self.make_client(opener).generate_json("system", {})
        self.assertEqual(len(opener.calls), 2)
        self.assertNotIn("secret-response", str(raised.exception))

    def test_invalid_http_json_also_has_one_format_retry(self):
        opener = FakeOpener(b"not-json", chat("{}"))
        self.assertEqual(self.make_client(opener).generate_json("system", {}), {})
        self.assertEqual(len(opener.calls), 2)

    def test_http_errors_are_safe_and_never_retried(self):
        for status in (302, 401, 429, 503):
            with self.subTest(status=status):
                failure = HTTPError("https://private.invalid/secret", status, "sensitive error", {}, io.BytesIO(b"credential-value"))
                opener = FakeOpener(failure)
                with self.assertRaises(LLMClientError) as raised:
                    self.make_client(opener).generate_json("system", {})
                self.assertEqual(raised.exception.status_code, status)
                self.assertEqual(len(opener.calls), 1)
                self.assertNotIn("private.invalid", str(raised.exception))
                self.assertNotIn("sensitive", str(raised.exception))
                self.assertNotIn("credential-value", str(raised.exception))

    def test_timeout_and_network_failures_do_not_expose_details(self):
        for error in (socket.timeout("secret-host"), URLError(socket.timeout("secret-host")), URLError("secret-host")):
            with self.subTest(error_type=type(error).__name__):
                opener = FakeOpener(error)
                with self.assertRaises(LLMClientError) as raised:
                    self.make_client(opener).generate_json("system", {})
                self.assertEqual(len(opener.calls), 1)
                self.assertNotIn("secret-host", str(raised.exception))

    def test_rejects_unsafe_base_urls_before_request(self):
        for base in (
            "http://example.invalid/v1",
            "https://user:password@example.invalid/v1",
            "https://example.invalid/v1?key=sensitive",
            "https://example.invalid/v1#fragment",
            "https://example.invalid:bad/v1",
            "https://example.invalid/unsafe path",
        ):
            with self.subTest(base=base):
                opener = FakeOpener()
                with self.assertRaises(LLMClientError) as raised:
                    self.make_client(opener, base_url=base)
                self.assertNotIn(base, str(raised.exception))
                self.assertEqual(opener.calls, [])

    def test_missing_configuration_uses_only_project_variables(self):
        configured = {"LLM_API_KEY": "offline-placeholder", "LLM_BASE_URL": "https://example.invalid/v1", "LLM_MODEL": "offline-model"}
        with patch.dict(os.environ, configured, clear=True), patch("src.llm_client.build_opener", return_value=FakeOpener(chat("{}"))):
            self.assertEqual(LLMClient().generate_json("system", {}), {})
        for missing in configured:
            remaining = dict(configured)
            remaining.pop(missing)
            remaining["OPENAI_API_KEY"] = "must-not-be-used"
            with self.subTest(missing=missing), patch.dict(os.environ, remaining, clear=True):
                with self.assertRaises(LLMClientError) as raised:
                    LLMClient()
                self.assertIn(missing, str(raised.exception))
                self.assertNotIn("must-not-be-used", str(raised.exception))

    def test_response_refusal_does_not_retry_or_expose_content(self):
        refused = {"choices": [{"message": {"refusal": "private refusal text", "content": None}}]}
        opener = FakeOpener(refused)
        with self.assertRaises(LLMClientError) as raised:
            self.make_client(opener).generate_json("system", {})
        self.assertEqual(len(opener.calls), 1)
        self.assertNotIn("private refusal text", str(raised.exception))

    def test_array_and_nonstandard_numbers_are_rejected(self):
        for content in ("[]", '{"value":NaN}', '{"value":Infinity}'):
            with self.subTest(content=content):
                opener = FakeOpener(chat(content), chat(content))
                with self.assertRaises(LLMClientError):
                    self.make_client(opener).generate_json("system", {})
                self.assertEqual(len(opener.calls), 2)

    def test_no_redirect_handler_blocks_forwarding(self):
        request = Request("https://example.invalid/v1", headers={"Authorization": "Bearer placeholder"})
        self.assertIsNone(_NoRedirect().redirect_request(request, None, 302, "", {}, "https://other.invalid"))

    def test_invalid_api_type_and_input_are_rejected(self):
        with self.assertRaises(LLMClientError):
            self.make_client(FakeOpener(), api_type="unknown")
        client = self.make_client(FakeOpener())
        with self.assertRaises(ValueError):
            client.generate_json("", {})
        with self.assertRaises(TypeError):
            client.generate_json("system", [])
        with self.assertRaises(ValueError):
            client.generate_json("system", {"invalid": float("nan")})


if __name__ == "__main__":
    unittest.main()
