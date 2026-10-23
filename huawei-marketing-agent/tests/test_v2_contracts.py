"""Runtime validation tests for workflow v2 typed contracts."""

import unittest

from src.v2_contracts import (
    ContractValidationError,
    validate_fact_check_result,
    validate_fact_record,
    validate_strategy_draft,
    validate_task_context,
)


def fact_record(**overrides):
    value = {
        "fact_id": "F1",
        "product_model": "Model Exact",
        "claim": "事实原文",
        "evidence_text": "事实原文",
        "source_ref": "docs/fact.md",
        "source_type": "official",
        "retrieved_at": "2026-10-22T00:00:00Z",
        "valid_until": None,
        "status": "supported",
    }
    return {**value, **overrides}


def task_context():
    return {
        "task_id": "task-1", "revision": 1, "source": "direct", "user_input": "raw input",
        "conversation": [{"role": "user", "text": "raw input", "at": "2026-10-22T00:00:00Z"}],
        "product_query": "Model Exact", "audience": "students", "platform": "小红书", "goal": "介绍",
        "scene": "开学季", "constraints": ["no price"],
        "field_status": {"product_query": "confirmed", "audience": "confirmed", "platform": "confirmed", "goal": "confirmed", "scene": "confirmed", "constraints": "confirmed"},
        "excluded_scenes": [], "opportunity_context": None, "fact_records": [fact_record()],
        "current_strategy_id": None, "current_strategy_version": None,
        "workflow_status": "collecting_requirements",
    }


def strategy_draft(**overrides):
    value = {
        "task_summary": "摘要", "topic": "主题",
        "audience": {"description": "学生", "basis": "用户输入", "basis_type": "user_provided"},
        "audience_need": "关注学习", "core_message": "核心表达", "content_angle": "场景切入",
        "content_format": "图文", "content_outline": [{"section": "开场", "purpose": "提出问题", "fact_references": ["F1"]}],
        "cta": "", "fact_references": ["F1"], "assumptions": [],
        "pending_confirmations": [], "risk_notes": [],
    }
    return {**value, **overrides}


class V2ContractTests(unittest.TestCase):
    def test_supported_fact_requires_verbatim_evidence_and_source(self):
        self.assertEqual(validate_fact_record(fact_record())["status"], "supported")
        for change in ({"evidence_text": ""}, {"source_ref": ""}):
            with self.subTest(change=change), self.assertRaises(ContractValidationError):
                validate_fact_record(fact_record(**change))

    def test_fact_confidence_cannot_be_added_as_contract_field(self):
        value = fact_record()
        value["confidence"] = 0.99
        with self.assertRaises(ContractValidationError):
            validate_fact_record(value)

    def test_task_requires_separate_original_input_and_conversation(self):
        task = validate_task_context(task_context())
        self.assertEqual(task["user_input"], task["conversation"][0]["text"])
        task["conversation"].append({"role": "user", "text": "new response", "at": "2026-10-22T00:01:00Z"})
        self.assertEqual(task["user_input"], "raw input")

    def test_cleared_field_must_have_empty_current_value(self):
        task = task_context()
        task["field_status"]["scene"] = "cleared"
        with self.assertRaises(ContractValidationError):
            validate_task_context(task)
        task["scene"] = ""
        self.assertEqual(validate_task_context(task)["field_status"]["scene"], "cleared")

    def test_task_context_rejects_cross_model_fact_mixing(self):
        task = task_context()
        task["fact_records"].append(fact_record(fact_id="F2", product_model="Different Model"))
        with self.assertRaises(ContractValidationError):
            validate_task_context(task)

    def test_strategy_workflow_state_requires_a_bound_strategy(self):
        task = task_context()
        task["workflow_status"] = "strategy_confirmed"
        with self.assertRaises(ContractValidationError):
            validate_task_context(task)

    def test_strategy_accepts_empty_cta_and_known_fact_references(self):
        result = validate_strategy_draft(strategy_draft(), {"F1"})
        self.assertEqual(result["cta"], "")

    def test_strategy_rejects_unknown_or_unverified_fact_references(self):
        with self.assertRaises(ContractValidationError):
            validate_strategy_draft(strategy_draft(), {"F2"})
        with self.assertRaises(ContractValidationError):
            validate_strategy_draft(strategy_draft(content_outline=[{"section": "a", "purpose": "b", "fact_references": ["F2"]}]), {"F1"})

    def test_supported_fact_check_requires_source_and_evidence(self):
        result = {
            "task_id": "task-1", "task_revision": 1, "claim": "事实原文", "status": "supported",
            "evidence": ["事实原文"], "source_refs": ["docs/fact.md"], "reason": "原文一致。", "suggested_action": "retain",
        }
        self.assertEqual(validate_fact_check_result(result)["status"], "supported")
        result["source_refs"] = []
        with self.assertRaises(ContractValidationError):
            validate_fact_check_result(result)


if __name__ == "__main__":
    unittest.main()
