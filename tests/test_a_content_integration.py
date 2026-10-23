"""Offline A/B bridge checks using synthetic A evidence and model fixtures."""
from copy import deepcopy
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "huawei-marketing-agent" / "tests"))
import app
from content_b.a_bridge import from_handoff, final_content, check_final
from content_b.contracts import ContentError, normalize
from content_b.providers import FactCheckAdapter
from content_b.service import ContentService
from content_b import http as content_http
from src import workflow_service as workflow
from src.final_check_service import FinalCheckService
from src.final_content_contracts import validate_final_content
from src.fact_checker import FactChecker
from src.workflow_service import TaskRepository
from test_final_check_service import confirmed, ReviewFixture, CLAIM
from test_strategy_service import SemanticFixture


class AContentIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.repo = TaskRepository()
        self.task, self.strategy = confirmed(self.repo)
        self.original_task = deepcopy(self.repo.get(self.task["task_id"]))
        def extract_plain_text_fact(value, payload):
            # The shared fixture assumes each input is a single assertion;
            # the bridge intentionally joins a title and body for copying.
            for field in value["fields"]:
                if field["field_path"] == "plain_text" and "\n\n" in field["text"]:
                    field["claims"] = [field["text"].split("\n\n", 1)[1]]
            for claim in value["fact_claims"]:
                if claim["field_path"] == "plain_text" and "\n\n" in claim["claim"]:
                    claim["claim"] = claim["claim"].split("\n\n", 1)[1]
        for name, value in (("REPOSITORY", self.repo), ("FINAL_CHECK_SERVICE", FinalCheckService(ReviewFixture(extract_plain_text_fact), FactChecker(SemanticFixture())))):
            item = patch.object(workflow, name, value)
            item.start()
            self.addCleanup(item.stop)
        self.binding = {"task_id": self.task["task_id"], "expected_revision": self.task["revision"],
            "strategy_id": self.strategy["strategy_id"], "strategy_version": self.strategy["strategy_version"]}

    def payload(self, body=CLAIM):
        return {"a_binding": deepcopy(self.binding), "content_hash": "synthetic-content-digest",
            "copy": {"title": "开学信息卡", "body": body, "cta": "", "hashtags": []},
            "images": [{"image_id": "img-synthetic", "role": "主题封面", "alt": "信息卡", "text_content": [], "url": "/synthetic.svg"}],
            "fact_references": [{"fact_id": "F1"}]}

    def test_handoff_only_adopted_eligible_facts_and_source_limits(self):
        request = normalize(from_handoff({**self.binding, "copy_mode": "assembly", "image_mode": "layout"}))
        self.assertEqual(request["strategy"]["audience"], "大学生")
        self.assertIsInstance(request["strategy"]["content_outline"][0], str)
        self.assertEqual([f["fact_id"] for f in request["product_context"]["facts"]], ["F1"])
        fact = request["product_context"]["facts"][0]
        self.assertEqual(fact["evidence_text"], CLAIM)
        self.assertEqual(fact["source_type"], "other")
        self.assertEqual(fact["status"], "supported")
        self.assertFalse(request["knowledge_source"]["live"])
        self.assertEqual(self.repo.get(self.task["task_id"])["revision"], self.task["revision"])
        self.assertEqual(self.repo.get(self.task["task_id"]), self.original_task)

    def test_forged_facts_or_confirmation_not_accepted_at_bridge(self):
        for extra in ({"confirmed": True}, {"product_context": {"facts": [{"status": "supported"}]}}):
            with self.assertRaises(ContentError):
                from_handoff({**self.binding, **extra})

    def test_stale_revision_and_foreign_task_rejected(self):
        for change in ({"expected_revision": self.task["revision"] - 1}, {"task_id": "task-" + "a" * 32}, {"strategy_id": "foreign"}):
            with self.assertRaises(ContentError):
                from_handoff({**self.binding, **change})

    def test_final_mapping_covers_images_tags_and_no_visual_attestation(self):
        payload = self.payload()
        payload["copy"]["hashtags"] = ["测试标签"]
        payload["images"][0]["text_content"] = ["屏幕尺寸：99 英寸。"]
        value = validate_final_content(final_content(payload))
        self.assertIn("屏幕尺寸：99 英寸。", value["images"][0]["caption"])
        self.assertIn("测试标签", value["plain_text"])
        self.assertEqual(value["images"][0]["status"], "unknown")
        self.assertEqual(value["fact_references"], ["F1"])

    def test_real_canonical_checker_result_text_usable_images_unknown(self):
        result = FactCheckAdapter().check(self.payload())
        self.assertEqual(result["status"], "passed")
        self.assertTrue(result["text_usable"])
        self.assertEqual(result["overall_status"], "partial")
        self.assertEqual(result["verified_image_ids"], [])
        self.assertEqual(result["image_check"]["status"], "unknown")
        self.assertGreater(result["a_result"]["task"]["revision"], self.task["revision"])

    def test_fake_parameter_not_granted_copy_eligibility(self):
        result = check_final(self.payload("屏幕尺寸：99 英寸。"))
        self.assertEqual(result["status"], "blocked")
        self.assertFalse(result["text_usable"])
        self.assertIsNone(result["usable_text"])

    def test_changed_requirement_rejects_stale_asset_strategy(self):
        self.repo.update(self.task["task_id"], self.task["revision"], {"updates": {"audience": "其他受众"}})
        with self.assertRaises(ContentError):
            check_final(self.payload())

    def test_changed_strategy_stops_generation_before_copy_model(self):
        request = from_handoff({**self.binding, "copy_mode": "llm"})
        self.repo.update(self.task["task_id"], self.task["revision"], {"updates": {"audience": "其他受众"}})
        with tempfile.TemporaryDirectory() as temp:
            provider = Mock()
            svc = ContentService(temp, copy_provider=provider)
            try:
                with self.assertRaises(ContentError):
                    svc.start(request)
                provider.generate.assert_not_called()
            finally:
                svc.shutdown()

    def test_readonly_refresh_route_does_not_advance_revision(self):
        server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        try:
            connection.request("GET", "/api/demo/tasks/" + self.task["task_id"])
            response = connection.getresponse()
            value = json.loads(response.read())
            self.assertEqual(response.status, 200)
            self.assertEqual(value["data"]["task"]["revision"], self.task["revision"])
            self.assertEqual(self.repo.get(self.task["task_id"])["revision"], self.task["revision"])
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(2)

    def test_http_generation_uses_server_handoff_not_client_facts(self):
        server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        svc = Mock()
        svc.start.return_value = {"job_id": "job-" + "a" * 32, "status": "pending", "asset_id": None}
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        try:
            with patch.object(content_http, "service", return_value=svc):
                connection.request("POST", "/api/content/from-handoff", json.dumps({**self.binding, "copy_mode": "assembly"}), {"Content-Type": "application/json"})
                response = connection.getresponse()
                value = json.loads(response.read())
            self.assertEqual(response.status, 202)
            self.assertTrue(value["success"])
            sent = svc.start.call_args.args[0]
            self.assertEqual(sent["a_binding"], self.binding)
            self.assertEqual(sent["product_context"]["facts"][0]["evidence_text"], CLAIM)
            self.assertEqual(sent["strategy"]["strategy_id"], self.strategy["strategy_id"])
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(2)


if __name__ == "__main__":
    unittest.main()
