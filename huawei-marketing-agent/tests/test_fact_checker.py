"""Offline provenance, semantic-assistance and concurrent workflow checks.

Every document and product parameter here is a synthetic test fixture.
No test sends a real model request or reads the user's knowledge base.
"""

import copy
import threading
import unittest
from unittest.mock import patch

from src.fact_checker import FactChecker
from src.llm_client import LLMClientError
import src.workflow_service as workflow
from src.workflow_service import TaskRepository, WorkflowError


MODEL = "HUAWEI MateBook X Pro 酷睿 Ultra 微绒典藏版"
SOURCE = {"mode": "local", "name": "fixture", "live": False, "status": "ok", "message": "synthetic"}


def record(text="屏幕尺寸：13.2 英寸。", **changes):
    return {
        "fact_id": "F1", "product_model": MODEL, "claim": text,
        "evidence_text": text, "source_ref": "P1/fixture.md", "source_type": "other",
        "retrieved_at": "2026-10-22T00:00:00Z", "valid_until": None, "status": "retrieved",
        **changes,
    }


def payload():
    return {"source": "direct", "user_input": "合成测试需求", "product_query": MODEL,
            "audience": "大学生", "platform": "小红书", "goal": "介绍事实", "scene": "开学季"}


def seed(repo, records=None, source=None, documents=None):
    facts = copy.deepcopy(records if records is not None else [record()])
    task = repo.create(payload())
    task = repo.begin_research(task["task_id"], task["revision"])
    return repo.complete_research(task["task_id"], task["revision"], facts,
        knowledge_source=source or SOURCE,
        evidence_documents=documents if documents is not None else [
            {"source_ref": r["source_ref"], "product_model": r["product_model"], "content": r["evidence_text"]}
            for r in facts
        ])


class SemanticFixture:
    def __init__(self, status="supported", invalid_quote=False, callback=None):
        self.status = status
        self.invalid_quote = invalid_quote
        self.callback = callback
        self.calls = []

    def generate_json(self, prompt, value):
        self.calls.append(copy.deepcopy(value))
        if self.callback:
            self.callback()
        return {"checks": [{"index": item["index"], "status": self.status, "evidence": [
            {"fact_id": r["fact_id"], "quote": "invented quotation" if self.invalid_quote else r["evidence_text"]}
            for r in item["records"]
        ]} for item in value["checks"]]}


class FactCheckerTests(unittest.TestCase):
    def check(self, claim=None, refs=None, records=None, documents=None, source=None, model=None):
        repo = TaskRepository()
        task = seed(repo, records, source, documents)
        task, context = repo.fact_check_snapshot(task["task_id"], task["revision"])
        item = {"claim": claim if claim is not None else task["fact_records"][0]["claim"],
                "fact_references": refs if refs is not None else ["F1"]}
        client = model or SemanticFixture()
        checked = FactChecker(client).check(task, [item], context)
        return checked, client

    def test_verbatim_fact_supported_by_actual_snapshot_not_retrieved_label(self):
        checked, model = self.check()
        self.assertEqual(checked["results"][0]["status"], "supported")
        self.assertEqual(checked["results"][0]["source_refs"], ["P1/fixture.md"])
        self.assertEqual(model.calls, [])
        self.assertFalse(checked["knowledge_source"]["live"])
        self.assertEqual(checked["source_types"]["F1"], "other")
        self.assertIn("可靠性", "".join(checked["warnings"]))
        self.assertIn("有效性未知", "".join(checked["warnings"]))

    def test_faithful_rewrite_uses_grounded_model_and_independent_guard(self):
        checked, model = self.check("这款电脑的屏幕尺寸为 13.2 英寸。")
        self.assertEqual(checked["results"][0]["status"], "supported")
        self.assertEqual(len(model.calls), 1)
        self.assertEqual(set(model.calls[0]), {"product_model", "checks"})
        self.assertNotIn("source_ref", str(model.calls[0]))

    def test_changed_number_or_unit_never_reaches_model(self):
        for claim in ("屏幕尺寸：15.2 英寸。", "屏幕尺寸：13.2 cm。", "屏幕尺寸。"):
            with self.subTest(claim=claim):
                checked, model = self.check(claim)
                self.assertEqual(checked["results"][0]["status"], "unsupported")
                self.assertEqual(model.calls, [])

    def test_swapped_parameter_values_cannot_pass_with_same_numbers(self):
        text = "内存：32 GB。\n存储容量：1 TB。"
        checked, model = self.check("内存：1 TB。存储容量：32 GB。", records=[record(text)])
        self.assertEqual(checked["results"][0]["status"], "unsupported")
        self.assertEqual(model.calls, [])

    def test_configuration_and_comparison_conditions_cannot_be_dropped(self):
        cases = [
            ("处理器：Ultra 9 185H，仅 Windows 销售 SKU。", "处理器：Ultra 9 185H。"),
            ("重量：约 1 kg。", "重量：1 kg。"),
            ("性能相比指定上代机型提升 10%。", "性能提升 10%。"),
            ("接口：USB-C，仅适用于 A 型配置。", "接口：USB-C，仅适用。"),
        ]
        for evidence, claim in cases:
            with self.subTest(claim=claim):
                checked, _ = self.check(claim, records=[record(evidence)])
                self.assertIn(checked["results"][0]["status"], {"unsupported", "needs_confirmation"})

    def test_2021_model_is_conflicting_even_with_valid_current_reference(self):
        checked, _ = self.check("HUAWEI MateBook X Pro 2021 屏幕尺寸为 13.2 英寸。")
        self.assertEqual(checked["results"][0]["status"], "conflicting")

    def test_no_source_and_forged_reference_are_unsupported(self):
        for refs in ([], ["forged-F99"], ["F1", "foreign-task-F2"]):
            checked, model = self.check(refs=refs)
            self.assertEqual(checked["results"][0]["status"], "unsupported")
            self.assertEqual(model.calls, [])

    def test_missing_raw_snapshot_requires_confirmation(self):
        checked, _ = self.check(documents=[])
        self.assertEqual(checked["results"][0]["status"], "needs_confirmation")

    def test_evidence_text_must_be_verbatim_in_original_document(self):
        checked, _ = self.check(documents=[{
            "source_ref": "P1/fixture.md", "product_model": MODEL, "content": "不同的原资料"
        }])
        self.assertEqual(checked["results"][0]["status"], "unsupported")
        self.assertEqual(checked["results"][0]["evidence"], [])

    def test_ui_demonstration_is_not_product_evidence(self):
        checked, _ = self.check(records=[record(source_ref="ui/prototype-data.js")])
        self.assertEqual(checked["results"][0]["status"], "unsupported")

    def test_conflicting_sources_block_only_related_parameter(self):
        facts = [record("重量：1 kg。"),
                 record("重量：2 kg。", fact_id="F2", source_ref="P1/other.md"),
                 record("屏幕尺寸：13.2 英寸。", fact_id="F3")]
        checked, _ = self.check(records=facts)
        self.assertEqual(checked["results"][0]["status"], "conflicting")
        self.assertEqual(set(checked["results"][0]["source_refs"]), {"P1/fixture.md", "P1/other.md"})
        self.assertEqual(checked["blocked_fact_ids"], ["F1", "F2"])
        checked, _ = self.check(claim=facts[2]["claim"], refs=["F3"], records=facts)
        self.assertEqual(checked["results"][0]["status"], "supported")

    def test_different_explicit_configurations_are_not_same_scope_conflict(self):
        facts = [record("内存：16 GB。\n仅 A 配置。"),
                 record("内存：32 GB。\n仅 B 配置。", fact_id="F2", source_ref="P1/b.md")]
        checked, _ = self.check(records=facts)
        self.assertEqual(checked["results"][0]["status"], "supported")
        self.assertEqual(checked["blocked_fact_ids"], [])

    def test_opposing_capabilities_and_prose_parameters_are_conflicts(self):
        for one, two in (("支持触控。", "不支持触控。"), ("内存为 16 GB。", "内存为 32 GB。"),
                         ("内存：16 GB（仅 A 配置）。", "内存：32 GB（仅 A 配置）。")):
            checked, _ = self.check(records=[record(one), record(two, fact_id="F2", source_ref="P1/other.md")])
            self.assertEqual(checked["results"][0]["status"], "conflicting")
            self.assertEqual(checked["blocked_fact_ids"], ["F1", "F2"])

    def test_unsupported_offer_is_not_inferred_from_stable_product_parameter(self):
        checked, model = self.check("今日到手价 4999 元，立减 1000 元。")
        self.assertEqual(checked["results"][0]["status"], "unsupported")
        self.assertEqual(model.calls, [])

    def test_local_or_expired_activity_needs_confirmation(self):
        text = "优惠 100 元，适用门店 A，有效期截至 2099-12-31。"
        for expiry in (None, "2000-01-01T00:00:00Z", "2099-12-31T23:59:59Z"):
            checked, _ = self.check(records=[record(text, valid_until=expiry)])
            self.assertEqual(checked["results"][0]["status"], "needs_confirmation")

    def test_live_commercial_claim_requires_actual_scope_and_explicit_validity(self):
        source = {**SOURCE, "mode": "ima", "live": True}
        checked, _ = self.check(records=[record("优惠 100 元。", valid_until="2099-12-31T00:00:00Z")], source=source)
        self.assertEqual(checked["results"][0]["status"], "needs_confirmation")

    def test_user_need_and_scene_inference_never_gain_fact_eligibility(self):
        for claim in ("大学生希望提高学习效率。", "适合大学生并提高学习效率。"):
            checked, _ = self.check(claim, records=[record(claim)])
            self.assertEqual(checked["results"][0]["status"], "not_applicable")

    def test_invalid_semantic_quote_is_rejected(self):
        checked, _ = self.check("这款电脑的屏幕尺寸为 13.2 英寸。", model=SemanticFixture(invalid_quote=True))
        self.assertEqual(checked["results"][0]["status"], "needs_confirmation")
        self.assertEqual(checked["errors"][0]["code"], "FACT_CHECK_RESPONSE_INVALID")
        self.assertEqual(checked["diagnostics"]["failure_type"], "response_schema")

    def test_model_supported_is_insufficient_for_new_claim(self):
        checked, _ = self.check("屏幕尺寸为 13.2 英寸，并获得人体工学认证。")
        self.assertEqual(checked["results"][0]["status"], "needs_confirmation")

    def test_negation_and_alternative_options_cannot_be_removed(self):
        for evidence, claim in (("不支持触控。", "支持触控。"), ("内存：16 GB 或 32 GB。", "内存：32 GB。")):
            checked, _ = self.check(claim, records=[record(evidence)])
            self.assertNotEqual(checked["results"][0]["status"], "supported")

    def test_negation_cannot_be_reversed(self):
        checked, model = self.check("支持触控。", records=[record("不支持触控。")])
        self.assertEqual(checked["results"][0]["status"], "unsupported")
        self.assertEqual(model.calls, [])


class FactCheckWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.repo = TaskRepository()
        self.task = seed(self.repo)
        self.previous_repo = workflow.REPOSITORY
        self.previous_checker = workflow.FACT_CHECKER
        workflow.set_repository(self.repo)
        workflow.set_fact_checker(FactChecker(SemanticFixture()))
        self.addCleanup(workflow.set_repository, self.previous_repo)
        self.addCleanup(workflow.set_fact_checker, self.previous_checker)

    def request(self, claims=None, task=None):
        task = task or self.task
        return workflow.dispatch("/api/facts/check", {
            "task_id": task["task_id"], "expected_revision": task["revision"],
            "claims": claims or [{"claim": record()["claim"], "fact_references": ["F1"]}],
        })

    def test_partial_pass_is_api_success_and_preserves_unrelated_eligibility(self):
        status, response = self.request([
            {"claim": record()["claim"], "fact_references": ["F1"]},
            {"claim": "售价 4999 元。", "fact_references": ["F1"]},
        ])
        self.assertEqual(status, 200)
        self.assertTrue(response["success"])
        checked = response["data"]["fact_check"]
        self.assertEqual(checked["counts"]["supported"], 1)
        self.assertEqual(checked["counts"]["unsupported"], 1)
        self.assertEqual(checked["eligible_fact_ids"], ["F1"])
        self.assertEqual(checked["task_revision"], self.task["revision"])
        self.assertEqual(checked["saved_task_revision"], self.task["revision"] + 1)
        self.assertEqual(response["data"]["task"]["fact_records"][0]["status"], "supported")
        history = self.repo.get_fact_checks(self.task["task_id"])
        self.assertEqual(history[0]["retrieved_fact_records"][0]["status"], "retrieved")
        history[0]["valid"] = False
        self.assertTrue(self.repo.get_fact_checks(self.task["task_id"])[0]["valid"])

    def test_retrieval_never_accepts_upstream_supported_label(self):
        repo = TaskRepository()
        task = seed(repo, [record(status="supported")])
        self.assertEqual(task["fact_records"][0]["status"], "retrieved")
        self.assertEqual(repo._eligible_fact_ids(task), set())

    def test_supported_rewrite_does_not_grant_original_candidate_full_eligibility(self):
        status, response = self.request([{"claim": "这款电脑的屏幕尺寸为 13.2 英寸。", "fact_references": ["F1"]}])
        self.assertEqual(status, 200)
        self.assertEqual(response["data"]["fact_check"]["results"][0]["status"], "supported")
        self.assertEqual(response["data"]["fact_check"]["eligible_fact_ids"], [])
        self.assertEqual(response["data"]["task"]["fact_records"][0]["status"], "retrieved")

    def test_product_change_or_clear_invalidates_check_but_retains_audit_basis(self):
        _, response = self.request()
        task = response["data"]["task"]
        changed = self.repo.update(task["task_id"], task["revision"], {
            "user_input": "清空产品", "clear_fields": ["product_query"], "updates": {},
        })
        self.assertEqual(changed["fact_records"], [])
        history = self.repo.get_fact_checks(task["task_id"])
        self.assertFalse(history[0]["valid"])
        self.assertEqual(history[0]["retrieved_fact_records"][0]["evidence_text"], record()["evidence_text"])
        self.assertEqual(self.repo._eligible_fact_ids(changed), set())

    def test_new_evidence_invalidates_previous_checks(self):
        _, response = self.request()
        task = response["data"]["task"]
        started = self.repo.begin_research(task["task_id"], task["revision"])
        fresh = self.repo.complete_research(task["task_id"], started["revision"], [record("屏幕尺寸：15.2 英寸。")])
        self.assertFalse(self.repo.get_fact_checks(task["task_id"])[0]["valid"])
        self.assertEqual(self.repo._eligible_fact_ids(fresh), set())

    def test_client_cannot_submit_evidence_or_supported(self):
        for extra in ({"status": "supported"}, {"source_ref": "P1/forged.md"}, {"evidence": "fake"}):
            status, response = self.request([{"claim": "陈述", "fact_references": ["F1"], **extra}])
            self.assertEqual(status, 400)
            self.assertEqual(response["error"]["code"], "INVALID_REQUEST")
        self.assertEqual(self.repo.get(self.task["task_id"])["revision"], self.task["revision"])

    def test_model_exception_is_safe_and_does_not_discard_independent_success(self):
        model = SemanticFixture()
        with patch.object(model, "generate_json", side_effect=RuntimeError("Authorization PRIVATE_SENTINEL")):
            workflow.set_fact_checker(FactChecker(model))
            status, response = self.request([
                {"claim": record()["claim"], "fact_references": ["F1"]},
                {"claim": "这款电脑的屏幕尺寸为 13.2 英寸。", "fact_references": ["F1"]},
            ])
        self.assertEqual(status, 502)
        self.assertFalse(response["success"])
        batch = response["data"]["fact_check"]
        self.assertEqual(batch["counts"]["supported"], 1)
        self.assertEqual(batch["counts"]["needs_confirmation"], 1)
        self.assertEqual(batch["eligible_fact_ids"], ["F1"])
        self.assertIn("recovery", response["data"])
        self.assertNotIn("PRIVATE_SENTINEL", str(response))

    def test_expired_response_after_concurrent_product_clear_never_writes(self):
        entered, release, cleared = threading.Event(), threading.Event(), threading.Event()
        model = SemanticFixture(callback=lambda: (entered.set(), release.wait(timeout=3)))
        workflow.set_fact_checker(FactChecker(model))
        result = []
        worker = threading.Thread(target=lambda: result.append(self.request([
            {"claim": "这款电脑的屏幕尺寸为 13.2 英寸。", "fact_references": ["F1"]}
        ])))
        worker.start()
        self.assertTrue(entered.wait(timeout=2))

        def clear():
            self.repo.update(self.task["task_id"], self.task["revision"], {"user_input": "清空", "clear_fields": ["product_query"]})
            cleared.set()

        updater = threading.Thread(target=clear)
        updater.start()
        try:
            self.assertTrue(cleared.wait(timeout=1), "external model call must not hold repository lock")
        finally:
            release.set()
            worker.join(timeout=3)
            updater.join(timeout=3)
        self.assertEqual(result[0][0], 409)
        self.assertEqual(result[0][1]["error"]["code"], "VERSION_CONFLICT")
        self.assertEqual(self.repo.get(self.task["task_id"])["fact_records"], [])
        self.assertEqual(self.repo.get_fact_checks(self.task["task_id"]), [])

    def test_claims_cannot_use_fact_from_another_task(self):
        other = seed(self.repo, [record(fact_id="OTHER-F1")])
        status, response = self.request([{"claim": record()["claim"], "fact_references": ["OTHER-F1"]}])
        self.assertEqual(status, 200)
        self.assertEqual(response["data"]["fact_check"]["counts"]["unsupported"], 1)
        self.assertEqual(self.repo.get(other["task_id"])["fact_records"][0]["status"], "retrieved")

    def test_duplicate_refs_and_empty_claim_batch_are_rejected(self):
        body = {"task_id": self.task["task_id"], "expected_revision": self.task["revision"]}
        for claims in ([], [{"claim": "陈述", "fact_references": ["F1", "F1"]}]):
            status, response = workflow.dispatch("/api/facts/check", {**body, "claims": claims})
            self.assertEqual(status, 400)
            self.assertEqual(response["error"]["code"], "INVALID_REQUEST")


if __name__ == "__main__":
    unittest.main()
