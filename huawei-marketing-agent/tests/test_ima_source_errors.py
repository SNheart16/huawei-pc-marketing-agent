"""Offline checks for machine-readable, credential-free source failures."""

import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from src.ima_client import ImaClient, ImaClientError


class SourceErrorTests(unittest.TestCase):
    def test_subprocess_timeout_is_explicit(self):
        client = ImaClient()
        with patch.object(client, "_check_credentials"), \
                patch.object(Path, "is_file", return_value=True), \
                patch("src.ima_client.subprocess.run", side_effect=subprocess.TimeoutExpired("node", 1)):
            with self.assertRaises(ImaClientError) as caught:
                client.call_api("openapi/wiki/v1/search_knowledge_base", {"query": "example"})
        self.assertEqual(caught.exception.kind, "timeout")

    def test_document_failure_is_structured_and_stops_reads(self):
        client = ImaClient()
        name = "test knowledge base"
        query = "Example PC"
        bases = {"info_list": [{"id": "test-kb", "name": name}], "is_end": True}
        hits = {"info_list": [
            {"media_id": "a", "title": query + " A.md", "media_type": 7},
            {"media_id": "b", "title": query + " B.md", "media_type": 7},
        ], "is_end": True}
        for failure in (
            ImaClientError("safe", code=220021),
            ImaClientError("safe", kind="timeout"),
            ImaClientError("safe", code=110010),
        ):
            with self.subTest(kind=failure.kind), \
                    patch.object(client, "search_knowledge_base", return_value=bases), \
                    patch.object(client, "search_knowledge", return_value=hits), \
                    patch.object(client, "_populate_document", side_effect=failure) as populate:
                result = client.retrieve_product_documents(query, name)
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["source_error"], {"code": failure.code, "kind": failure.kind})
            self.assertEqual(populate.call_count, 1)
            self.assertEqual(len(result["documents"]), 2)
            self.assertIsNone(result["selected_product_model"])

    def test_permission_and_invalid_input_are_not_availability_errors(self):
        client = ImaClient()
        for code in (110001, 110030, 110021):
            with self.subTest(code=code), self.assertRaises(ImaClientError) as caught:
                client._response_data({"code": code, "msg": "untrusted raw message"}, "read")
            self.assertIsNone(caught.exception.kind)
            self.assertNotIn("untrusted", str(caught.exception))

    def test_partial_read_does_not_masquerade_as_ambiguous_input(self):
        client = ImaClient()
        bases = {"info_list": [{"id": "test-kb", "name": "test"}], "is_end": True}
        hits = {"info_list": [
            {"media_id": "a", "title": "Example PC A.md", "media_type": 7},
            {"media_id": "b", "title": "Example PC B.md", "media_type": 7},
        ], "is_end": True}

        def populate(document, item, warnings):
            if item["media_id"] == "b":
                raise ImaClientError("safe", code=220021)
            document["content"] = "product_model: HUAWEI Example PC Signature Edition"

        with patch.object(client, "search_knowledge_base", return_value=bases), \
                patch.object(client, "search_knowledge", return_value=hits), \
                patch.object(client, "_populate_document", side_effect=populate):
            result = client.retrieve_product_documents("Example PC", "test")
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["candidate_models"]), 1)
        self.assertIsNone(result["selected_product_model"])
        self.assertEqual(result["source_error"]["code"], 220021)

    def test_media_http_unavailable_and_timeout_are_explicit(self):
        client = ImaClient()
        url = "https://skb.ima.myqcloud.com/example.md"
        for failure, expected in (
            (HTTPError(url, 503, "private raw message", {}, None), "unavailable"),
            (HTTPError(url, 403, "private raw message", {}, None), None),
            (URLError(TimeoutError("private raw message")), "timeout"),
            (URLError("private raw message"), None),
        ):
            with self.subTest(expected=expected), \
                    patch("src.ima_client.build_opener") as opener:
                opener.return_value.open.side_effect = failure
                with self.assertRaises(ImaClientError) as caught:
                    client._read_url(url, {})
            self.assertEqual(caught.exception.kind, expected)
            self.assertNotIn("private", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
