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

    def issue_card(self, field="scenario_inputs.usage.text", mode="single", options=None):
        self.model.return_value = result(
            question="选择或描述主要使用场景。",
            question_card={
                "field": field,
                "mode": mode,
                "options": options or ["课程资料整理", "文档处理"],
                "allow_free_text": True,
            },
        )
        status, response = dispatch("/api/agent/understand", full_request())
        self.assertEqual(status, 201)
        card = response["data"]["understanding"]["question_cards"][0]
        return response["data"]["task"], card

    def test_scenario_inputs_are_normalized_as_unverified_user_context(self):
        status, response = dispatch("/api/agent/understand", full_request(
            scenario_inputs={
                "time": {"text": "秋季开学季"},
                "store": {"location_text": "校园周边门店", "nearby_landmarks": ["用户提供的学校"]},
                "usage": {"text": "阅读课程资料、整理笔记"},
            },
        ))
        self.assertEqual(status, 201)
        task = response["data"]["task"]
        self.assertEqual(task["scenario_inputs"]["time"]["field_status"], "confirmed")
        self.assertEqual(task["scenario_inputs"]["time"]["source"], "user_input")
        self.assertEqual(task["scenario_inputs"]["time"]["verification_status"], "unverified")
        self.assertEqual(task["scenario_inputs"]["store"]["nearby_landmarks"], ["用户提供的学校"])
        self.assertEqual(task["scene"], "开学季")
        self.assertNotEqual(task["scene"], task["scenario_inputs"]["usage"]["text"])

    def test_scenario_input_rejects_client_provenance_or_verified_status(self):
        for value in (
            {"time": {"text": "某时段", "source": "official"}},
            {"usage": {"text": "某场景", "verification_status": "verified"}},
        ):
            with self.subTest(value=value):
                status, response = dispatch("/api/agent/understand", full_request(scenario_inputs=value))
                self.assertEqual(status, 400)
                self.assertEqual(response["error"]["code"], "INVALID_REQUEST")

    def test_question_card_is_server_issued_and_bound_to_saved_revision(self):
        task, card = self.issue_card()
        self.assertEqual(card["issued_revision"], task["revision"])
        self.assertTrue(card["question_id"].startswith("question-"))
        self.assertTrue(all(option["option_id"].startswith("option-") for option in card["options"]))
        self.assertEqual(card["field"], "scenario_inputs.usage.text")
        self.assertEqual(card["mode"], "single")

    def test_filled_scenario_card_is_suppressed_without_repeating_question(self):
        self.model.return_value = result(
            question="你希望顾客实际如何使用电脑？",
            question_card={
                "field": "scenario_inputs.usage.text",
                "mode": "single",
                "options": ["课程资料整理"],
                "allow_free_text": True,
            },
        )
        _, response = dispatch("/api/agent/understand", full_request(
            scenario_inputs={"usage": {"text": "阅读课程资料"}},
        ))
        self.assertEqual(response["data"]["understanding"]["questions"], [])
        self.assertEqual(response["data"]["understanding"]["question_cards"], [])

    def test_single_card_answer_uses_server_option_label_and_accepts_free_text_override(self):
        task, card = self.issue_card()
        selected = card["options"][0]
        self.model.return_value = result(scenario_updates={"usage": {"text": "复习课程资料"}})
        status, response = dispatch("/api/agent/continue", {
            "task_id": task["task_id"], "expected_revision": task["revision"],
            "user_input": "使用场景改为复习课程资料。",
            "card_answers": [{"question_id": card["question_id"], "option_ids": [selected["option_id"]]}],
        })
        self.assertEqual(status, 200)
        updated = response["data"]["task"]
        self.assertEqual(updated["scenario_inputs"]["usage"]["text"], "复习课程资料")
        self.assertEqual(updated["scenario_inputs"]["usage"]["source"], "user_input")
        self.assertEqual(updated["scenario_inputs"]["usage"]["verification_status"], "unverified")
        self.assertEqual(response["data"]["interpretation"]["question_cards"], [])

    def test_multiple_card_answer_replaces_landmark_array_and_discards_client_labels(self):
        task, card = self.issue_card(
            field="scenario_inputs.store.nearby_landmarks", mode="multiple",
            options=["校门", "图书馆", "用户自定义选项"],
        )
        options = card["options"]
        self.model.return_value = result()
        status, response = dispatch("/api/agent/continue", {
            "task_id": task["task_id"], "expected_revision": task["revision"],
            "user_input": "附近地标按卡片选择。",
            "card_answers": [{
                "question_id": card["question_id"],
                "option_ids": [options[0]["option_id"], options[1]["option_id"]],
            }],
        })
        self.assertEqual(status, 200)
        updated = response["data"]["task"]
        self.assertEqual(updated["scenario_inputs"]["store"]["nearby_landmarks"], ["校门", "图书馆"])
        self.assertEqual(updated["scenario_inputs"]["store"]["nearby_landmarks_status"], "confirmed")

    def test_invalid_card_answers_are_atomic(self):
        task, card = self.issue_card()
        invalid_answers = (
            [{"question_id": card["question_id"], "option_ids": ["forged-option"]}],
            [{"question_id": card["question_id"], "option_ids": [card["options"][0]["option_id"]] * 2}],
            [{"question_id": card["question_id"], "option_ids": [item["option_id"] for item in card["options"]]}],
            [{"question_id": card["question_id"], "option_ids": [card["options"][0]["option_id"]], "labels": ["伪造标签"]}],
        )
        for answer in invalid_answers:
            with self.subTest(answer=answer):
                status, response = dispatch("/api/agent/continue", {
                    "task_id": task["task_id"], "expected_revision": task["revision"],
                    "user_input": "这轮不会被保存。", "card_answers": answer,
                })
                self.assertEqual(status, 400)
                self.assertEqual(response["error"]["code"], "INVALID_CARD_ANSWER")
                current = self.repo.get(task["task_id"])
                self.assertEqual(current["revision"], task["revision"])
                self.assertEqual(current["conversation"], task["conversation"])

    def test_card_answer_rejects_stale_or_cross_task_question(self):
        task, card = self.issue_card()
        answer = {"question_id": card["question_id"], "option_ids": [card["options"][0]["option_id"]]}
        other = self.repo.create(full_request())
        status, response = dispatch("/api/agent/continue", {
            "task_id": other["task_id"], "expected_revision": other["revision"],
            "user_input": "尝试跨任务提交卡片。", "card_answers": [answer],
        })
        self.assertEqual(status, 409)
        self.assertEqual(response["error"]["code"], "QUESTION_CARD_STALE")
        self.assertEqual(self.repo.get(other["task_id"])["revision"], other["revision"])

        self.model.return_value = result()
        _, changed = dispatch("/api/agent/continue", {
            "task_id": task["task_id"], "expected_revision": task["revision"],
            "user_input": "改为普通文字回复", "updates": {"audience": "研究生"},
        })
        latest = changed["data"]["task"]
        status, response = dispatch("/api/agent/continue", {
            "task_id": task["task_id"], "expected_revision": latest["revision"],
            "user_input": "重放旧卡片。", "card_answers": [answer],
        })
        self.assertEqual(status, 409)
        self.assertEqual(response["error"]["code"], "QUESTION_CARD_STALE")

    def test_card_answer_and_explicit_same_field_update_requires_resolution(self):
        task, card = self.issue_card()
        status, response = dispatch("/api/agent/continue", {
            "task_id": task["task_id"], "expected_revision": task["revision"],
            "user_input": "同时提交两种不同场景值。",
            "scenario_inputs": {"usage": {"text": "处理实验数据"}},
            "card_answers": [{"question_id": card["question_id"], "option_ids": [card["options"][0]["option_id"]]}],
        })
        self.assertEqual(status, 409)
        self.assertEqual(response["error"]["code"], "INPUT_CONFLICT")
        self.assertEqual(self.repo.get(task["task_id"])["revision"], task["revision"])

    def test_explicit_scenario_clear_cannot_be_restored_by_model(self):
        task, _ = self.issue_card()
        self.model.return_value = result(scenario_updates={"usage": {"text": "历史场景"}})
        status, response = dispatch("/api/agent/continue", {
            "task_id": task["task_id"], "expected_revision": task["revision"],
            "user_input": "不再指定使用场景。", "clear_fields": ["scenario_inputs.usage.text"],
        })
        self.assertEqual(status, 200)
        usage = response["data"]["task"]["scenario_inputs"]["usage"]
        self.assertEqual(usage["text"], "")
        self.assertEqual(usage["field_status"], "cleared")

    def test_opportunity_scenario_provenance_is_preserved(self):
        self.model.return_value = result(scenario_updates={"time": {"text": "秋季开学季"}})
        _, response = dispatch("/api/agent/understand", {
            "source": "opportunity", "user_input": "按机会内容准备推广。",
            "opportunity_context": {"scenario_inputs": {"time": {"text": "秋季开学季"}}},
        })
        time_input = response["data"]["task"]["scenario_inputs"]["time"]
        self.assertEqual(time_input["text"], "秋季开学季")
        self.assertEqual(time_input["source"], "opportunity")
        self.assertEqual(time_input["verification_status"], "unverified")


if __name__ == "__main__":
    unittest.main()
