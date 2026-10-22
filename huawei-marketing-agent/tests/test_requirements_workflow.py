"""Offline tests for LLM-backed requirement workflow orchestration."""

import unittest
from unittest.mock import patch

from src.requirements_service import RequirementsError, _normalize_result
from src.workflow_service import TaskRepository, WorkflowError, dispatch, set_repository


MODEL = "HUAWEI MateBook X Pro"


def result(**changes):
    value = {
        "summary": "已理解当前推广需求。",
        "updates": {},
        "clear_fields": [],
        "excluded_scenes": [],
        "question": None,
    }
    value.update(changes)
    return value


def full_request(**changes):
    value = {
        "source": "direct",
        "user_input": "原始用户需求必须保留",
        "product_query": MODEL,
        "audience": "大学新生",
        "platform": "小红书",
        "goal": "介绍资料支持的学习场景",
        "scene": "开学季",
        "constraints": ["不写价格"],
    }
    value.update(changes)
    return value


class RequirementsWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.repo = TaskRepository()
        set_repository(self.repo)
        model_patch = patch("src.workflow_service.interpret_requirements", return_value=result())
        self.model = model_patch.start()
        self.addCleanup(model_patch.stop)

    def test_vague_request_has_one_question_and_preserves_original_input(self):
        self.model.return_value = result(
            summary="用户想准备电脑相关内容，产品型号和其他条件尚待补充。",
            updates={"audience": "大学新生"},
            question="这次要推广的产品或具体型号是什么？",
        )
        status, response = dispatch("/api/agent/understand", {
            "user_input": "想给大学新生准备一条开学季的电脑内容。",
        })
        task = response["data"]["task"]
        self.assertEqual(status, 201)
        self.assertEqual(task["user_input"], "想给大学新生准备一条开学季的电脑内容。")
        self.assertEqual(task["audience"], "大学新生")
        self.assertEqual(task["workflow_status"], "collecting_requirements")
        self.assertEqual(len(response["data"]["understanding"]["questions"]), 1)
        self.assertIn("product_query", response["data"]["missing_information"])

    def test_complete_request_is_ready_for_strategy_without_fact_claim(self):
        status, response = dispatch("/api/agent/understand", full_request())
        self.assertEqual(status, 201)
        self.assertTrue(response["success"])
        self.assertEqual(response["data"]["task"]["workflow_status"], "ready_for_strategy")
        self.assertEqual(response["data"]["next_action"], "research_product")
        self.assertEqual(response["data"]["understanding"]["questions"], [])
        self.assertEqual(response["data"]["task"]["fact_records"], [])
        self.assertEqual(response["data"]["task"]["field_status"]["product_query"], "confirmed")

    def test_opportunity_context_is_retained_and_can_ground_fields(self):
        self.model.return_value = result(updates={"audience": "大学新生", "scene": "开学季"})
        status, response = dispatch("/api/agent/understand", {
            "source": "opportunity",
            "user_input": "按机会方向准备内容",
            "opportunity_context": {"audience": "大学新生", "scene": "开学季", "source_label": "opportunity-board"},
        })
        task = response["data"]["task"]
        self.assertEqual(status, 201)
        self.assertEqual(task["source"], "opportunity")
        self.assertEqual(task["opportunity_context"]["source_label"], "opportunity-board")
        self.assertEqual(task["audience"], "大学新生")
        self.assertEqual(task["scene"], "开学季")

    def test_continue_changes_only_explicitly_grounded_audience(self):
        _, created = dispatch("/api/agent/understand", full_request())
        task = created["data"]["task"]
        self.model.return_value = result(
            summary="受众已调整为研究生，其余需求沿用。",
            updates={"audience": "研究生"},
        )
        status, response = dispatch("/api/agent/continue", {
            "task_id": task["task_id"], "expected_revision": task["revision"],
            "user_input": "受众改为研究生。", "updates": {}, "clear_fields": [],
        })
        updated = response["data"]["task"]
        self.assertEqual(status, 200)
        self.assertEqual(updated["user_input"], "原始用户需求必须保留")
        self.assertEqual(updated["audience"], "研究生")
        self.assertEqual(updated["product_query"], MODEL)
        self.assertEqual(updated["scene"], "开学季")
        self.assertEqual(updated["platform"], "小红书")
        self.assertEqual(updated["field_status"]["audience"], "confirmed")

    def test_explicit_scene_clear_cannot_be_restored_from_history_or_model(self):
        _, created = dispatch("/api/agent/understand", full_request())
        task = created["data"]["task"]
        self.model.return_value = result(updates={"scene": "开学季"})
        status, response = dispatch("/api/agent/continue", {
            "task_id": task["task_id"], "expected_revision": task["revision"],
            "user_input": "清空场景，不指定场景。", "updates": {}, "clear_fields": ["scene"],
        })
        updated = response["data"]["task"]
        self.assertEqual(status, 200)
        self.assertEqual(updated["scene"], "")
        self.assertEqual(updated["field_status"]["scene"], "cleared")
        self.assertEqual(updated["workflow_status"], "ready_for_strategy")

    def test_cleared_opportunity_scene_is_not_restored_from_opportunity_context(self):
        self.model.return_value = result(updates={"scene": "开学季"})
        _, created = dispatch("/api/agent/understand", {
            "source": "opportunity",
            "user_input": "按机会方向准备内容",
            "opportunity_context": {"scene": "开学季", "source_label": "opportunity-board"},
        })
        task = created["data"]["task"]
        self.assertEqual(task["scene"], "开学季")

        status, response = dispatch("/api/agent/continue", {
            "task_id": task["task_id"], "expected_revision": task["revision"],
            "user_input": "这次不使用开学季场景。", "updates": {}, "clear_fields": ["scene"],
        })

        updated = response["data"]["task"]
        self.assertEqual(status, 200)
        self.assertEqual(updated["scene"], "")
        self.assertEqual(updated["field_status"]["scene"], "cleared")

        status, response = dispatch("/api/agent/continue", {
            "task_id": updated["task_id"], "expected_revision": updated["revision"],
            "user_input": "不添加新要求。", "updates": {}, "clear_fields": [],
        })
        self.assertEqual(status, 200)
        self.assertEqual(response["data"]["task"]["scene"], "")
        self.assertEqual(response["data"]["task"]["field_status"]["scene"], "cleared")
        self.assertNotIn("scene", response["data"]["missing_information"])

    def test_opportunity_cannot_replace_current_confirmed_audience(self):
        _, created = dispatch("/api/agent/understand", full_request(
            source="opportunity", audience="研究生",
            opportunity_context={"audience": "大学新生", "source_label": "opportunity-board"},
        ))
        task = created["data"]["task"]
        self.model.return_value = result(updates={"audience": "大学新生"})
        status, response = dispatch("/api/agent/continue", {
            "task_id": task["task_id"], "expected_revision": task["revision"],
            "user_input": "其他要求不变。", "updates": {}, "clear_fields": [],
        })
        self.assertEqual(status, 200)
        self.assertEqual(response["data"]["task"]["audience"], "研究生")

    def test_question_targets_one_missing_field_not_a_known_field(self):
        self.model.return_value = result(question="受众是谁？平台是什么？")
        _, response = dispatch("/api/agent/understand", {"user_input": "准备内容", "audience": "大学新生"})
        questions = response["data"]["understanding"]["questions"]
        self.assertEqual(questions, ["这次要推广的产品或具体型号是什么？"])
        self.assertNotIn("audience", response["data"]["missing_information"])

    def test_continue_model_failure_retains_explicit_edits_and_turn(self):
        _, created = dispatch("/api/agent/understand", full_request())
        task = created["data"]["task"]
        self.model.side_effect = RequirementsError("LLM_UNAVAILABLE", "安全模型错误")
        status, response = dispatch("/api/agent/continue", {
            "task_id": task["task_id"], "expected_revision": task["revision"],
            "user_input": "受众改为研究生", "updates": {"audience": "研究生"}, "clear_fields": ["scene"],
        })
        saved = response["data"]["task"]
        self.assertEqual(status, 502)
        self.assertEqual(saved["user_input"], task["user_input"])
        self.assertEqual(saved["audience"], "研究生")
        self.assertEqual(saved["scene"], "")
        self.assertGreater(saved["revision"], task["revision"])
        self.assertEqual(self.repo.get(saved["task_id"]), saved)
        self.assertEqual(saved["conversation"][-1]["text"], "受众改为研究生")

    def test_model_failure_keeps_saved_task_and_returns_recovery(self):
        self.model.side_effect = RequirementsError("LLM_UNAVAILABLE", "安全模型错误")
        status, response = dispatch("/api/agent/understand", {"user_input": "新任务原文"})
        self.assertEqual(status, 502)
        self.assertFalse(response["success"])
        self.assertEqual(response["error"]["code"], "LLM_UNAVAILABLE")
        self.assertEqual(response["data"]["task"]["user_input"], "新任务原文")
        self.assertIn("recovery", response["data"])

    def test_expired_llm_result_is_rejected_after_concurrent_revision_change(self):
        def race(task, *args):
            self.repo.update(task["task_id"], task["revision"], {
                "task_id": task["task_id"], "expected_revision": task["revision"],
                "user_input": "并发补充", "updates": {"audience": "研究生"}, "clear_fields": [],
            })
            return result(updates={"platform": "小红书"})

        self.model.side_effect = race
        status, response = dispatch("/api/agent/understand", {
            "user_input": "准备相关内容",
            "platform": "门店朋友圈",
        })
        self.assertEqual(status, 409)
        self.assertEqual(response["error"]["code"], "VERSION_CONFLICT")
        self.assertEqual(self.repo.get(response["error"]["details"]["task_id"])["audience"], "研究生")

    def test_model_output_cannot_set_server_owned_or_unknown_fields(self):
        with self.assertRaises(RequirementsError):
            _normalize_result({**result(), "task_id": "model-controlled"})


if __name__ == "__main__":
    unittest.main()
