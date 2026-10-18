"""Offline source-selection tests; no credentials, files, or network are used."""

import os
import unittest
from unittest.mock import patch

from src.ima_client import ImaClientError
from src.knowledge_service import KnowledgeService


def result(status="success", label="document", source_error=None):
    value = {
        "status": status,
        "query": "test product",
        "selected_product_model": "test product" if status == "success" else None,
        "candidate_models": [],
        "documents": [{"document_title": label}],
        "warnings": [],
        "missing_information": [],
    }
    if source_error is not None:
        value["source_error"] = source_error
    return value


def client_error(code=None, kind=None):
    error = ImaClientError("Safe test failure", code=code)
    error.kind = kind
    return error


class FakeClient:
    def __init__(self, response=None, error=None):
        self.response = response if response is not None else result()
        self.error = error
        self.calls = []

    def retrieve_product_documents(self, product_query, kb_name):
        self.calls.append((product_query, kb_name))
        if self.error is not None:
            raise self.error
        return self.response


class KnowledgeServiceTests(unittest.TestCase):
    def test_ima_mode_never_calls_local(self):
        online = FakeClient(result(label="online"))
        local = FakeClient()
        actual = KnowledgeService("ima", online, local).retrieve_product_documents("test product")
        self.assertEqual(actual["documents"][0]["document_title"], "online")
        self.assertEqual(actual["knowledge_source"]["mode"], "ima")
        self.assertTrue(actual["knowledge_source"]["live"])
        self.assertEqual(len(online.calls), 1)
        self.assertEqual(local.calls, [])

    def test_local_mode_never_calls_ima(self):
        online = FakeClient(error=client_error())
        local = FakeClient(result(label="local"))
        actual = KnowledgeService("local", online, local).retrieve_product_documents("test product")
        self.assertEqual(actual["documents"][0]["document_title"], "local")
        self.assertEqual(actual["knowledge_source"]["mode"], "local")
        self.assertFalse(actual["knowledge_source"]["live"])
        self.assertEqual(online.calls, [])

    def test_auto_success_preserves_online_source(self):
        online, local = FakeClient(), FakeClient()
        actual = KnowledgeService("auto", online, local).retrieve_product_documents("test product")
        self.assertEqual(actual["knowledge_source"]["mode"], "ima")
        self.assertEqual(local.calls, [])

    def test_auto_quota_exception_falls_back_without_online_documents(self):
        online = FakeClient(error=client_error(code=220021))
        local = FakeClient(result(label="local only"))
        actual = KnowledgeService("auto", online, local).retrieve_product_documents("test product")
        self.assertEqual(actual["documents"], [{"document_title": "local only"}])
        self.assertEqual(actual["knowledge_source"]["status"], "quota_limited")
        self.assertEqual(actual["knowledge_source"]["mode"], "local")
        self.assertEqual(len(local.calls), 1)

    def test_auto_quota_partial_result_discards_online_documents(self):
        online = FakeClient(result("partial", "online partial", {"code": 220021, "kind": "quota_limited"}))
        local = FakeClient(result(label="local only"))
        actual = KnowledgeService("auto", online, local).retrieve_product_documents("test product")
        self.assertEqual(actual["documents"], [{"document_title": "local only"}])
        self.assertNotIn("source_error", actual)
        self.assertEqual(actual["knowledge_source"]["status"], "quota_limited")

    def test_auto_explicit_timeout_and_service_unavailable_fall_back(self):
        for kind in ("timeout", "unavailable"):
            with self.subTest(kind=kind):
                online = FakeClient(error=client_error(kind=kind))
                local = FakeClient()
                actual = KnowledgeService("auto", online, local).retrieve_product_documents("test product")
                self.assertEqual(actual["knowledge_source"]["mode"], "local")
                self.assertEqual(actual["knowledge_source"]["status"], "unavailable")

    def test_conflict_and_needs_input_take_precedence_over_quota(self):
        for status in ("conflict", "needs_input"):
            with self.subTest(status=status):
                online = FakeClient(result(status, source_error={"code": 220021, "kind": "quota_limited"}))
                local = FakeClient()
                actual = KnowledgeService("auto", online, local).retrieve_product_documents("test product")
                self.assertEqual(actual["status"], status)
                self.assertEqual(actual["knowledge_source"]["mode"], "ima")
                self.assertEqual(local.calls, [])

    def test_unstructured_warning_never_triggers_fallback(self):
        response = result("partial")
        response["warnings"] = ["220021 quota timeout unavailable"]
        local = FakeClient()
        actual = KnowledgeService("auto", FakeClient(response), local).retrieve_product_documents("test product")
        self.assertEqual(actual["knowledge_source"]["mode"], "ima")
        self.assertEqual(local.calls, [])

    def test_permission_credentials_and_ordinary_errors_do_not_fall_back(self):
        for code in (None, 403, 220001):
            with self.subTest(code=code):
                error = client_error(code=code)
                local = FakeClient()
                with self.assertRaises(ImaClientError) as raised:
                    KnowledgeService("auto", FakeClient(error=error), local).retrieve_product_documents("test product")
                self.assertIs(raised.exception, error)
                self.assertEqual(local.calls, [])

    def test_ima_mode_does_not_fall_back_on_quota(self):
        local = FakeClient()
        with self.assertRaises(ImaClientError):
            KnowledgeService("ima", FakeClient(error=client_error(code=220021)), local).retrieve_product_documents("test product")
        self.assertEqual(local.calls, [])

    def test_mode_uses_environment_and_defaults_to_ima(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(KnowledgeService().mode, "ima")
        with patch.dict(os.environ, {"KNOWLEDGE_SOURCE_MODE": " local "}, clear=True):
            self.assertEqual(KnowledgeService().mode, "local")
        for mode in ("", "invalid"):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                KnowledgeService(mode)

    def test_blank_query_is_rejected_before_either_source(self):
        online, local = FakeClient(), FakeClient()
        with self.assertRaises(ValueError):
            KnowledgeService("auto", online, local).retrieve_product_documents(" ")
        self.assertEqual(online.calls, [])
        self.assertEqual(local.calls, [])

    def test_provenance_does_not_mutate_client_result(self):
        original = result()
        actual = KnowledgeService("local", local_client=FakeClient(original)).retrieve_product_documents("test product")
        self.assertNotIn("knowledge_source", original)
        self.assertNotIn(":\\", actual["knowledge_source"]["message"])

    def test_bad_client_response_has_safe_error(self):
        with self.assertRaisesRegex(TypeError, "must return a dict"):
            KnowledgeService("local", local_client=FakeClient([])).retrieve_product_documents("test product")

    def test_local_unavailable_preserves_failure_status(self):
        response = result("partial")
        response["knowledge_source"] = {"status": "unavailable", "message": "withheld"}
        actual = KnowledgeService("local", local_client=FakeClient(response)).retrieve_product_documents("test product")
        self.assertEqual(actual["knowledge_source"]["status"], "unavailable")
        self.assertFalse(actual["knowledge_source"]["live"])

    def test_failed_local_fallback_reports_both_sources_unavailable(self):
        response = result("partial")
        response["knowledge_source"] = {"status": "unavailable", "message": "withheld"}
        online = FakeClient(error=client_error(code=220021))
        actual = KnowledgeService("auto", online, FakeClient(response)).retrieve_product_documents("test product")
        self.assertEqual(actual["knowledge_source"]["status"], "unavailable")
        self.assertIn("本地只读副本也不可用", actual["knowledge_source"]["message"])
        self.assertNotIn("withheld", actual["knowledge_source"]["message"])


if __name__ == "__main__":
    unittest.main()
