"""Offline HTTP bridge checks; no LLM or knowledge API calls."""

import contextlib
import http.client
import io
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


class FrontendServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def request(self, payload=None, raw=None, headers=None, method="POST", path="/api/run"):
        body = raw if raw is not None else json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            connection.request(method, path, body=body, headers=headers or {"Content-Type": "application/json"})
            response = connection.getresponse()
            return response.status, json.loads(response.read().decode("utf-8"))
        finally:
            connection.close()

    def test_real_backend_import(self):
        self.assertTrue(callable(app.run_agent))
        self.assertEqual(app.run_agent.__module__, "src.agent")
        self.assertEqual(Path(sys.modules["src.agent"].__file__).resolve(),
                         app.BACKEND_DIR / "src" / "agent.py")

    def test_health_only_reports_safe_import_status(self):
        status, result = self.request(method="GET", path="/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(result["backend"])
        self.assertIsNone(result["detail"])

    def test_exact_input_and_json_v1_result_passthrough(self):
        task = {name: "真实联调" for name in app.INPUT_KEYS}
        returned = {"schema_version": "1.0", "status": "partial", "content": {
            "plain_text": "可复制文案", "images": [{"name": "待确认图片", "url": None, "status": "unknown"}]},
            "evidence": [{"fact": "原文", "source_ref": "P1/资料.md"}],
            "checks": {"facts": [], "images": [], "compliance": [], "risks": [], "missing_information": [], "questions": []}}
        with patch.object(app, "run_agent", return_value=returned) as agent:
            status, result = self.request({**task, "unused": "不透传"})
        agent.assert_called_once_with(task)
        self.assertEqual(status, 200)
        self.assertEqual(result, returned)

    def test_empty_product_calls_real_agent_needs_input(self):
        task = {name: "已有输入" for name in app.INPUT_KEYS}
        task["product_query"] = ""
        status, result = self.request(task)
        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "needs_input")
        self.assertEqual(result["schema_version"], "1.0")
        self.assertIsNone(result["content"])
        self.assertTrue(result["checks"]["questions"])

    def test_null_inputs_remain_safe(self):
        status, result = self.request({"product_query": None})
        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "needs_input")
        self.assertIsNone(result["content"])

    def test_exception_does_not_expose_details_or_log_traceback(self):
        private = "Authorization: PRIVATE_SENTINEL"
        log = io.StringIO()
        with patch.object(app, "run_agent", side_effect=RuntimeError(private)), contextlib.redirect_stderr(log):
            status, result = self.request({})
        self.assertEqual(status, 500)
        self.assertEqual(result["status"], "error")
        self.assertIsNone(result["content"])
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(result) + log.getvalue())
        self.assertNotIn("Traceback", log.getvalue())

    def test_backend_unavailable_does_not_offer_mock(self):
        with patch.object(app, "run_agent", None):
            status, result = self.request({})
        self.assertEqual(status, 503)
        self.assertNotIn("模拟", json.dumps(result, ensure_ascii=False))

    def test_bad_json_hides_supplied_text(self):
        status, result = self.request(raw=b'{"PRIVATE_SENTINEL":')
        self.assertEqual(status, 400)
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(result))

    def test_non_object_is_rejected(self):
        status, result = self.request(raw=b"[]")
        self.assertEqual(status, 400)
        self.assertIsNone(result["content"])

    def test_malformed_content_length_is_safe(self):
        status, result = self.request(raw=b"{}", headers={"Content-Length": "invalid"})
        self.assertEqual(status, 400)
        self.assertEqual(result["status"], "error")

    def test_oversized_body_is_rejected_before_agent(self):
        with patch.object(app, "run_agent") as agent:
            status, _ = self.request(raw=b"{}", headers={"Content-Length": str(app.MAX_BODY + 1)})
        self.assertEqual(status, 400)
        agent.assert_not_called()

    def test_non_text_field_is_rejected(self):
        with patch.object(app, "run_agent") as agent:
            status, _ = self.request({"product_query": {"invalid": True}})
        self.assertEqual(status, 400)
        agent.assert_not_called()

    def test_non_dict_backend_result_is_safe(self):
        with patch.object(app, "run_agent", return_value=[]):
            status, result = self.request({})
        self.assertEqual(status, 502)
        self.assertEqual(result["schema_version"], "1.0")

    def test_non_json_backend_result_is_safe(self):
        with patch.object(app, "run_agent", return_value={"invalid": object()}):
            status, result = self.request({})
        self.assertEqual(status, 502)
        self.assertEqual(result["status"], "error")


if __name__ == "__main__":
    unittest.main()
