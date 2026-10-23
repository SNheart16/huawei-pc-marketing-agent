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
import src.workflow_service as workflow_service
from src.product_research_service import ResearchResult
from src.fact_checker import FactChecker
from src.strategy_service import StrategyService
from src.final_check_service import FinalCheckService


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

    def setUp(self):
        workflow_service.reset_repository()
        self.requirements_model = patch("src.workflow_service.interpret_requirements", return_value={
            "summary": "离线测试需求摘要",
            "updates": {}, "clear_fields": [], "excluded_scenes": [],
            "question": "这次要推广的产品或具体型号是什么？",
        })
        self.requirements_model.start()
        self.addCleanup(self.requirements_model.stop)

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

    def test_v2_understand_route_returns_task_and_separate_envelope(self):
        request = {
            "source": "direct", "user_input": "为开学季准备内容",
            "product_query": "MateBook", "audience": "大学生", "scene": "开学季",
            "platform": "小红书", "goal": "内容介绍", "constraints": [],
        }
        status, result = self.request(request, path="/api/agent/understand")
        self.assertEqual(status, 201)
        self.assertEqual(set(result), {"success", "data", "error"})
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["task"]["workflow_status"], "ready_for_strategy")
        self.assertEqual(result["data"]["understanding"]["implementation_status"], "IMPLEMENTED")

    def test_v2_continue_clear_and_version_conflict(self):
        _, created = self.request({"user_input": "需求", "scene": "开学季"}, path="/api/agent/understand")
        task = created["data"]["task"]
        payload = {
            "task_id": task["task_id"], "expected_revision": task["revision"],
            "user_input": "先不指定场景", "updates": {}, "clear_fields": ["scene"],
        }
        status, updated = self.request(payload, path="/api/agent/continue")
        self.assertEqual(status, 200)
        self.assertEqual(updated["data"]["task"]["scene"], "")
        self.assertEqual(updated["data"]["task"]["field_status"]["scene"], "cleared")
        stale_status, stale = self.request(payload, path="/api/agent/continue")
        self.assertEqual(stale_status, 409)
        self.assertEqual(stale["error"]["code"], "VERSION_CONFLICT")

    def test_v2_fact_check_requires_product_before_checking(self):
        _, created = self.request({"user_input": "需求"}, path="/api/agent/understand")
        task = created["data"]["task"]
        payload = {"task_id": task["task_id"], "expected_revision": task["revision"], "claims": [{"claim": "一句陈述", "fact_references": []}]}
        status, result = self.request(payload, path="/api/facts/check")
        self.assertEqual(status, 409)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "PRODUCT_REQUIRED")

    def test_v2_research_route_uses_current_task_product_and_saves_real_adapter_shape(self):
        _, created = self.request({
            "source": "direct", "user_input": "完整需求", "product_query": "Model Exact",
            "audience": "大学生", "scene": "开学季", "platform": "小红书", "goal": "介绍事实",
        }, path="/api/agent/understand")
        task = created["data"]["task"]
        record = {
            "fact_id": "fixture-F1", "product_model": "Model Exact", "claim": "离线证据",
            "evidence_text": "离线证据", "source_ref": "P1/fixture.md", "source_type": "other",
            "retrieved_at": "2026-10-22T00:00:00Z", "valid_until": None, "status": "retrieved",
        }
        research = ResearchResult({
            "status": "partial", "query": "Model Exact", "selected_product_model": "Model Exact",
            "candidate_models": [], "documents": [], "fact_records": [record],
            "knowledge_source": {"mode": "local", "name": "任德耀新建华为PC知识库", "live": False,
                                 "status": "ok", "message": "离线 fixture"},
            "warnings": [], "missing_information": [], "next_action": "check_facts",
        }, evidence_documents=[{"source_ref": record["source_ref"], "product_model": "Model Exact", "content": "离线证据"}])
        payload = {"task_id": task["task_id"], "expected_revision": task["revision"]}
        with patch.object(workflow_service.RESEARCH_SERVICE, "retrieve_product_facts", return_value=research) as retrieve:
            status, result = self.request(payload, path="/api/agent/research")
            stale_status, stale = self.request(payload, path="/api/agent/research")
        retrieve.assert_called_once_with("Model Exact")
        self.assertEqual(status, 200)
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["task"]["fact_records"], [record])
        self.assertEqual(result["data"]["task"]["workflow_status"], "ready_for_strategy")
        self.assertEqual(result["data"]["next_action"], "check_facts")
        self.assertEqual(stale_status, 409)
        self.assertEqual(stale["error"]["code"], "VERSION_CONFLICT")

        saved = result["data"]["task"]
        check_request = {
            "task_id": saved["task_id"], "expected_revision": saved["revision"],
            "claims": [{"claim": record["claim"], "fact_references": [record["fact_id"]]},
                       {"claim": "优惠 100 元", "fact_references": [record["fact_id"]]},
                       {"claim": "外部伪造陈述", "fact_references": ["forged-F99"]}],
        }
        status, checked = self.request(check_request, path="/api/facts/check")
        self.assertEqual(status, 200)
        self.assertTrue(checked["success"])
        batch = checked["data"]["fact_check"]
        self.assertEqual(batch["counts"]["supported"], 1)
        self.assertEqual(batch["counts"]["unsupported"], 2)
        self.assertEqual(batch["eligible_fact_ids"], [record["fact_id"]])
        self.assertFalse(batch["knowledge_source"]["live"])
        self.assertEqual(batch["results"][0]["source_refs"], [record["source_ref"]])
        self.assertNotIn("evidence_documents", json.dumps(checked))
        stale_status, stale = self.request(check_request, path="/api/facts/check")
        self.assertEqual(stale_status, 409)
        self.assertEqual(stale["error"]["code"], "VERSION_CONFLICT")

    def test_v2_fact_check_rejects_client_status_and_source(self):
        for injected in ({"status": "supported"}, {"source_ref": "forged.md"}):
            with self.subTest(injected=injected):
                status, response = self.request({
                    "task_id": "unused", "expected_revision": 1,
                    "claims": [{"claim": "陈述", "fact_references": [], **injected}],
                }, path="/api/facts/check")
                self.assertEqual(status, 400)
                self.assertEqual(response["error"]["code"], "INVALID_REQUEST")

    def test_v2_research_rejects_frontend_supplied_evidence(self):
        with patch.object(workflow_service.RESEARCH_SERVICE, "retrieve_product_facts") as retrieve:
            status, result = self.request({
                "task_id": "not-used", "expected_revision": 1, "fact_records": [],
            }, path="/api/agent/research")
        self.assertEqual(status, 400)
        self.assertEqual(result["error"]["code"], "INVALID_REQUEST")
        retrieve.assert_not_called()

    def test_v2_strategy_confirmation_route_binds_task_revision_and_strategy_version(self):
        repo = workflow_service.REPOSITORY
        task = repo.create({
            "source": "direct", "user_input": "需求", "product_query": "Model Exact",
            "audience": "大学新生", "platform": "小红书", "goal": "介绍事实", "scene": "开学季",
        })
        task = repo.begin_research(task["task_id"], task["revision"])
        task = repo.complete_research(task["task_id"], task["revision"], [{
            "fact_id": "F1", "product_model": "Model Exact", "claim": "事实原文",
            "evidence_text": "事实原文", "source_ref": "docs/fact.md", "source_type": "official",
            "retrieved_at": "2026-10-22T00:00:00Z", "valid_until": None, "status": "supported",
        }], knowledge_source={"mode": "local", "name": "fixture", "live": False, "status": "ok", "message": "fixture"},
            evidence_documents=[{"source_ref": "docs/fact.md", "product_model": "Model Exact", "content": "事实原文"}])
        self.assertEqual(task["fact_records"][0]["status"], "retrieved")
        check_status, checked = self.request({
            "task_id": task["task_id"], "expected_revision": task["revision"],
            "claims": [{"claim": "事实原文", "fact_references": ["F1"]}],
        }, path="/api/facts/check")
        self.assertEqual(check_status, 200)
        self.assertEqual(checked["data"]["fact_check"]["eligible_fact_ids"], ["F1"])
        task = checked["data"]["task"]
        draft = {
            "task_summary": "摘要", "topic": "主题",
            "audience": {"description": "大学新生", "basis": "用户输入", "basis_type": "user_provided"},
            "audience_need": "了解产品", "core_message": "事实原文", "content_angle": "场景切入",
            "content_format": "图文", "content_outline": [{"section": "开场", "purpose": "提问", "fact_references": []}],
            "cta": "", "fact_references": ["F1"], "assumptions": ["了解产品"],
            "pending_confirmations": [], "risk_notes": [],
        }
        class StrategyModel:
            def generate_json(self, prompt, payload):
                if "fields" in payload:
                    return {"fields": [
                        {**item, "kind": "factual" if item["field_path"] == "core_message" else "planning",
                         "claims": [item["text"]] if item["field_path"] == "core_message" else []}
                        for item in payload["fields"]
                    ]}
                return {"strategy": draft, "fact_claims": [
                    {"field_path": "core_message", "claim": "事实原文", "fact_references": ["F1"]},
                ]}
        with patch.object(workflow_service, "STRATEGY_SERVICE", StrategyService(StrategyModel())):
            status, generated = self.request({"task_id": task["task_id"], "expected_revision": task["revision"]},
                                             path="/api/strategy/generate")
        self.assertEqual(status, 200)
        self.assertTrue(generated["success"])
        self.assertEqual(generated["data"]["next_action"], "confirm_strategy")
        self.assertEqual(generated["data"]["fact_check"]["counts"]["supported"], 1)
        task, strategy = generated["data"]["task"], generated["data"]["strategy"]
        self.assertEqual(strategy["confirmation_status"], "pending")
        status, premature = self.request({
            "task_id": task["task_id"], "expected_revision": task["revision"],
            "strategy_id": strategy["strategy_id"], "strategy_version": strategy["strategy_version"],
        }, path="/api/strategy/handoff")
        self.assertEqual(status, 409)
        self.assertEqual(premature["error"]["code"], "STRATEGY_NOT_CONFIRMED")
        status, result = self.request({
            "task_id": task["task_id"], "expected_revision": task["revision"],
            "strategy_id": strategy["strategy_id"], "strategy_version": strategy["strategy_version"],
        }, path="/api/strategy/confirm")
        self.assertEqual(status, 200)
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["task"]["workflow_status"], "strategy_confirmed")
        self.assertEqual(result["data"]["strategy"]["confirmation_status"], "confirmed")

        status, handoff = self.request({
            "task_id": task["task_id"], "expected_revision": result["data"]["task"]["revision"],
            "strategy_id": strategy["strategy_id"], "strategy_version": strategy["strategy_version"],
        }, path="/api/strategy/handoff")
        self.assertEqual(status, 200)
        self.assertEqual(handoff["data"]["handoff"]["fact_records"][0]["fact_id"], "F1")
        self.assertFalse(handoff["data"]["handoff"]["knowledge_source"]["live"])
        self.assertEqual(handoff["data"]["handoff"]["image_status"], "unknown")
        self.assertNotIn("evidence_documents", handoff["data"]["handoff"])

        final_request = {
            "task_id": result["data"]["task"]["task_id"],
            "expected_revision": result["data"]["task"]["revision"],
            "strategy_id": strategy["strategy_id"], "strategy_version": strategy["strategy_version"],
            "content": {"title": "标题", "body": "事实原文", "cta": "", "plain_text": "事实原文", "images": []},
        }
        class FinalModel:
            def generate_json(self, prompt, payload):
                return {"fields": [
                    {**field, "kind": "factual" if field["text"] == "事实原文" else "planning",
                     "claims": [field["text"]] if field["text"] == "事实原文" else []}
                    for field in payload["fields"]
                ], "fact_claims": [
                    {"field_path": field["field_path"], "claim": field["text"], "fact_references": ["F1"]}
                    for field in payload["fields"] if field["text"] == "事实原文"
                ], "issues": []}
        with patch.object(workflow_service, "FINAL_CHECK_SERVICE", FinalCheckService(FinalModel())):
            status, final_check = self.request(final_request, path="/api/facts/check-final")
            stale_status, stale = self.request(final_request, path="/api/facts/check-final")
        self.assertEqual(status, 200)
        self.assertTrue(final_check["success"])
        checked = final_check["data"]["final_check"]
        self.assertEqual(checked["text_check"]["status"], "passed")
        self.assertEqual(checked["text_check"]["counts"]["supported"], 2)
        self.assertEqual(checked["usable_text"]["plain_text"], "事实原文")
        self.assertEqual(checked["strategy_id"], strategy["strategy_id"])
        self.assertEqual(checked["strategy_version"], strategy["strategy_version"])
        self.assertEqual(checked["content_version"], 1)
        self.assertEqual(len(checked["content_digest"]), 64)
        self.assertEqual(checked["image_check"]["status"], "unknown")
        self.assertFalse(checked["image_check"]["visual_check_performed"])
        self.assertEqual(checked["overall"]["status"], "partial")
        self.assertFalse(checked["overall"]["ready_to_publish"])
        self.assertEqual(stale_status, 409)
        self.assertEqual(stale["error"]["code"], "VERSION_CONFLICT")

    def test_v2_strategy_generate_without_checked_facts_never_calls_model(self):
        task = workflow_service.REPOSITORY.create({
            "source": "direct", "user_input": "合成需求", "product_query": "SYNTHETIC_MODEL",
            "audience": "大学生", "platform": "小红书", "goal": "介绍信息", "scene": "开学季",
        })
        task = workflow_service.REPOSITORY.begin_research(task["task_id"], task["revision"])
        task = workflow_service.REPOSITORY.complete_research(task["task_id"], task["revision"], [])
        with patch.object(workflow_service, "StrategyService") as service:
            status, result = self.request({"task_id": task["task_id"], "expected_revision": task["revision"]},
                                          path="/api/strategy/generate")
        self.assertEqual(status, 409)
        self.assertEqual(result["error"]["code"], "NO_VERIFIED_FACTS")
        service.assert_not_called()

    def test_v2_strategy_endpoints_reject_client_controlled_fields(self):
        with patch.object(workflow_service, "StrategyService") as service:
            status, result = self.request({"task_id": "not-used", "expected_revision": 1,
                                          "fact_records": [], "confirmation_status": "confirmed"},
                                         path="/api/strategy/generate")
        self.assertEqual(status, 400)
        self.assertEqual(result["error"]["code"], "INVALID_REQUEST")
        service.assert_not_called()
        status, _ = self.request({"task_id": "not-used", "expected_revision": 1,
                                 "strategy_id": "S1", "strategy_version": 1, "confirmed": True},
                                path="/api/strategy/confirm")
        self.assertEqual(status, 400)
        status, result = self.request({"task_id": "not-used", "expected_revision": 1,
                                      "strategy_id": "S1", "strategy_version": 1.0},
                                     path="/api/strategy/handoff")
        self.assertEqual(status, 400)
        self.assertEqual(result["error"]["code"], "INVALID_REQUEST")

    def test_legacy_v1_route_still_passes_through_unchanged(self):
        task = {name: "兼容输入" for name in app.INPUT_KEYS}
        expected = {"schema_version": "1.0", "status": "needs_input", "scenario": {}, "evidence": [], "content": None, "checks": {}}
        with patch.object(app, "run_agent", return_value=expected) as agent:
            status, result = self.request(task, path="/api/run")
        self.assertEqual(status, 200)
        self.assertEqual(result, expected)
        agent.assert_called_once_with(task)


if __name__ == "__main__":
    unittest.main()
