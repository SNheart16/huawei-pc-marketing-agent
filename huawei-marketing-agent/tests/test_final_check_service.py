"""Offline final-review acceptance. All facts and models are synthetic fixtures."""

import copy
import re
import threading
import unittest
from unittest.mock import patch

from src.fact_checker import FactChecker
from src.final_check_service import FinalCheckService, FinalCheckError
from src.final_content_contracts import content_digest, content_texts, validate_final_content
from src.llm_client import LLMClientError
from src.strategy_service import StrategyService, review_confirmation_gaps
from src.v2_contracts import ContractValidationError
from src.workflow_service import TaskRepository, WorkflowError
import src.workflow_service as workflow
from test_strategy_service import ModelFixture, SemanticFixture, MODEL, SOURCE


CLAIM = "屏幕尺寸：13.2 英寸。"


def confirmed(repo, claim=CLAIM):
    task = repo.create({"source": "direct", "user_input": "离线最终核查测试",
        "product_query": MODEL, "audience": "大学生", "platform": "小红书",
        "goal": "介绍有依据的信息", "scene": "开学季", "constraints": ["不写价格、优惠、个人体验"]})
    task = repo.begin_research(task["task_id"], task["revision"])
    record = {"fact_id": "F1", "product_model": MODEL, "claim": claim, "evidence_text": claim,
        "source_ref": "fixtures/F1.md", "source_type": "other", "status": "retrieved",
        "retrieved_at": "2026-10-22T00:00:00Z", "valid_until": None}
    task = repo.complete_research(task["task_id"], task["revision"], [record], knowledge_source=SOURCE,
        evidence_documents=[{"source_ref": record["source_ref"], "product_model": MODEL, "content": claim}])
    task, context = repo.fact_check_snapshot(task["task_id"], task["revision"])
    claims = [{"claim": claim, "fact_references": ["F1"]}]
    task, _ = repo.complete_fact_check(task, context, claims, FactChecker().check(task, claims, context))
    task, context, eligible = repo.strategy_snapshot(task["task_id"], task["revision"])
    assessment = StrategyService(ModelFixture()).generate(task, eligible, context)
    task, strategy = repo.add_strategy(task["task_id"], task["revision"], assessment["draft"], assessment=assessment, context=context)
    return repo.confirm_strategy(task["task_id"], task["revision"], strategy["strategy_id"], strategy["strategy_version"])


def content(body=CLAIM, **changes):
    return {"title": "开学信息卡", "body": body, "cta": "", "plain_text": body, "images": [], **changes}


class ReviewFixture:
    """Independent full-text extractor for deterministic offline evidence tests."""
    def __init__(self, mutate=None, callback=None, error=None):
        self.mutate, self.callback, self.error = mutate, callback, error
        self.calls = []

    def generate_json(self, prompt, payload):
        self.calls.append(copy.deepcopy(payload))
        if self.callback:
            self.callback()
        if self.error:
            raise self.error
        fields, mapping = [], []
        for field in payload["fields"]:
            text = field["text"]
            if text.startswith("不要写"):
                claims, kind = [], "constraint"
            elif re.search(r"屏幕尺寸|处理器|续航|优惠|\d+\s*元|2021", text):
                # Extract embedded claims, while retaining their conditions.
                claim = text.removeprefix("建议突出").removeprefix("采用双栏排版，突出")
                claims, kind = [claim], "factual"
            else:
                claims, kind = [], "planning"
            fields.append({**field, "kind": kind, "claims": claims})
            mapping.extend({"field_path": field["field_path"], "claim": c,
                            "fact_references": [] if re.search(r"优惠|\d+\s*元", c) else ["F1"]} for c in claims)
        result = {"fields": fields, "fact_claims": mapping, "issues": []}
        if self.mutate:
            self.mutate(result, payload)
        return result


class FinalCheckTests(unittest.TestCase):
    def setUp(self):
        self.repo = TaskRepository()
        for name, value in (("REPOSITORY", self.repo), ("FINAL_CHECK_SERVICE", None)):
            item = patch.object(workflow, name, value)
            item.start()
            self.addCleanup(item.stop)
        self.task, self.strategy = confirmed(self.repo)

    def service(self, review=None, checker=None):
        return FinalCheckService(review or ReviewFixture(), checker or FactChecker(SemanticFixture()))

    def check(self, draft=None, review=None, checker=None):
        task, context, facts = self.repo.strategy_snapshot(self.task["task_id"], self.task["revision"])
        return self.service(review, checker).check(task, self.strategy, facts, context, draft or content())

    def request(self, draft=None, *, task=None, strategy=None, service=None):
        task = task or self.repo.get(self.task["task_id"])
        strategy = strategy or self.strategy
        with patch.object(workflow, "FINAL_CHECK_SERVICE", service or self.service()):
            return workflow.dispatch("/api/facts/check-final", {
                "task_id": task["task_id"], "expected_revision": task["revision"],
                "strategy_id": strategy["strategy_id"], "strategy_version": strategy["strategy_version"],
                "content": draft or content(),
            })

    def test_supported_verbatim_text_is_usable_but_entire_creative_is_not_approved(self):
        draft = content()
        original = copy.deepcopy(draft)
        status, response = self.request(draft)
        self.assertEqual(status, 200)
        self.assertTrue(response["success"])
        checked = response["data"]["final_check"]
        self.assertEqual(checked["text_check"]["status"], "passed")
        self.assertEqual(checked["text_check"]["counts"]["supported"], 2)
        self.assertEqual(checked["overall"], {"status": "partial", "completed": False, "text_usable": True, "ready_to_publish": False})
        self.assertEqual(checked["usable_text"]["plain_text"], original["plain_text"])
        self.assertEqual(draft, original)
        self.assertEqual(checked["content_digest"], content_digest(draft))
        self.assertEqual(checked["strategy_id"], self.strategy["strategy_id"])
        self.assertFalse(checked["knowledge_source"]["live"])
        self.assertIn("other", "".join(checked["warnings"]))
        self.assertIn("有效性未知", "".join(checked["warnings"]))

    def test_faithful_rewrite_uses_semantic_checker(self):
        model = SemanticFixture()
        result = self.check(content("这款电脑的屏幕尺寸为 13.2 英寸。"), checker=FactChecker(model))
        self.assertEqual(result["text_check"]["status"], "passed")
        self.assertTrue(model.calls)

    def test_unreferenced_fake_number_is_found_and_blocked(self):
        result = self.check(content("屏幕尺寸：99 英寸。"))
        self.assertEqual(result["text_check"]["status"], "blocked")
        self.assertIsNone(result["usable_text"])
        self.assertTrue(result["text_check"]["blocking_items"])

    def test_every_customer_text_field_and_image_caption_is_independently_checked(self):
        for changes in ({"title": "屏幕尺寸：99 英寸。"}, {"cta": "今日优惠 1000 元。"},
                        {"selling_points": ["屏幕尺寸：99 英寸。"]}, {"tags": ["全天续航"]},
                        {"additional_text": ["屏幕尺寸：99 英寸。"]},
                        {"images": [{"name": "样图", "caption": "屏幕尺寸：99 英寸。", "url": None}]}):
            with self.subTest(changes=changes):
                result = self.check(content(**changes))
                self.assertNotEqual(result["text_check"]["status"], "passed")

    def test_changed_unit_and_removed_configuration_conditions_are_blocked(self):
        cases = [(CLAIM, "屏幕尺寸：13.2 cm。"),
                 ("处理器：测试 CPU A，仅适用 Windows 版本。", "处理器：测试 CPU A。")]
        for evidence, final in cases:
            with self.subTest(final=final):
                repo = TaskRepository()
                task, strategy = confirmed(repo, evidence)
                task, context, facts = repo.strategy_snapshot(task["task_id"], task["revision"])
                result = self.service().check(task, strategy, facts, context, content(final))
                self.assertNotEqual(result["text_check"]["status"], "passed")

    def test_mixed_2021_model_is_conflicting(self):
        result = self.check(content("HUAWEI MateBook X Pro 2021 屏幕尺寸：13.2 英寸。"))
        self.assertGreater(result["text_check"]["counts"]["conflicting"], 0)
        self.assertFalse(result["overall"]["text_usable"])

    def test_unverified_offer_without_any_citation_is_blocked(self):
        result = self.check(content("今日优惠 1000 元。"))
        self.assertGreater(result["text_check"]["counts"]["unsupported"], 0)

    def test_planning_and_constraints_are_not_product_facts(self):
        result = self.check(content(additional_text=["建议采用三张图呈现", "不要写证据未支持的参数"]))
        self.assertEqual(result["text_check"]["status"], "passed")
        self.assertTrue(all(item["check"]["status"] == "not_applicable" for item in result["text_check"]["results"]
                            if item["field_path"].startswith("additional_text")))

    def test_fact_embedded_in_advice_is_not_exempt(self):
        for text in ("建议突出电脑支持全天续航。", "采用双栏排版，突出其配备某处理器。"):
            with self.subTest(text=text):
                result = self.check(content(additional_text=[text]))
                self.assertNotEqual(result["text_check"]["status"], "passed")
                self.assertTrue(any(item["field_path"] == "additional_text[0]" for item in result["text_check"]["blocking_items"]))

    def test_supported_fact_embedded_in_advice_is_checked(self):
        result = self.check(content(additional_text=["建议突出" + CLAIM]))
        self.assertEqual(result["text_check"]["status"], "passed")
        self.assertTrue(any(item["field_path"] == "additional_text[0]" and item["check"]["status"] == "supported"
                            for item in result["text_check"]["results"]))

    def test_forged_client_references_cannot_be_silently_remapped(self):
        for draft in (content(fact_references=["FORGED"]), content(images=[{"source_ref": "forged.md"}]),
                      content(CLAIM + "[F999]")):
            with self.subTest(draft=draft):
                self.assertEqual(self.check(draft)["text_check"]["status"], "blocked")

    def test_forged_model_reference_is_explicitly_blocked(self):
        def mutate(value, payload):
            for item in value["fact_claims"]:
                item["fact_references"] = ["FORGED"]
        self.assertEqual(self.check(review=ReviewFixture(mutate))["text_check"]["status"], "blocked")

    def test_empty_images_are_unknown_and_not_a_visual_pass(self):
        result = self.check()
        self.assertEqual(result["image_check"]["status"], "unknown")
        self.assertEqual(result["image_check"]["confirmed_count"], 0)
        self.assertIn("空列表", "".join(result["image_check"]["missing_information"]))

    def test_claimed_confirmed_image_remains_unknown_without_downloading_url(self):
        review = ReviewFixture()
        result = self.check(content(images=[{"name": "图片待确认", "status": "confirmed", "url": "https://invalid.test/image"}]), review)
        self.assertEqual(result["image_check"]["unknown_count"], 1)
        self.assertEqual(result["image_check"]["confirmed_count"], 0)
        self.assertFalse(result["image_check"]["visual_check_performed"])
        self.assertEqual(result["image_check"]["items"][0]["embedded_text"], "unknown")
        self.assertNotIn("https://invalid.test", str(review.calls))

    def test_omitted_obvious_fact_cannot_hide_behind_planning_label(self):
        def mutate(value, payload):
            value["fact_claims"] = []
            for field in value["fields"]:
                field.update(kind="planning", claims=[])
        result = self.check(content("屏幕尺寸：99 英寸。"), ReviewFixture(mutate))
        self.assertEqual(result["text_check"]["status"], "needs_confirmation")
        self.assertFalse(result["overall"]["text_usable"])

    def test_incomplete_full_text_review_fails_safely(self):
        def mutate(value, payload):
            value["fields"].pop()
        with self.assertRaises(FinalCheckError) as raised:
            self.check(review=ReviewFixture(mutate))
        self.assertEqual(raised.exception.code, "FINAL_CHECK_RESPONSE_INVALID")

    def test_uncertain_classification_is_explicitly_pending_not_approved(self):
        def mutate(value, payload):
            value["fields"][0].update(kind="uncertain", claims=[])
        status, result = self.request(service=self.service(ReviewFixture(mutate)))
        self.assertEqual(status, 200)
        self.assertEqual(result["data"]["final_check"]["text_check"]["status"], "needs_confirmation")

    def test_user_constraint_and_strategy_mismatch_have_bound_quotes(self):
        for category in ("user_constraint", "strategy_mismatch", "exaggeration"):
            with self.subTest(category=category):
                def mutate(value, payload):
                    value["issues"] = [{"field_path": "title", "quote": "开学信息卡", "category": category}]
                self.assertEqual(self.check(review=ReviewFixture(mutate))["text_check"]["status"], "blocked")

    def test_obvious_absolute_and_personal_experience_violations_are_blocked(self):
        for text in ("行业第一", "我用这款电脑体验很好"):
            with self.subTest(text=text):
                self.assertEqual(self.check(content(additional_text=[text]))["text_check"]["status"], "blocked")

    def test_request_projection_keeps_only_needed_context_evidence_and_all_text(self):
        model = ReviewFixture()
        result = self.check(content(images=[{"name": "待确认", "url": None, "source": "来源待确认"}]), model)
        payload = model.calls[0]
        self.assertEqual(set(payload), {"task", "confirmed_strategy", "eligible_fact_records", "fields"})
        self.assertNotIn("conversation", str(payload))
        self.assertNotIn("evidence_documents", str(payload))
        self.assertEqual({f["field_path"] for f in payload["fields"]}, set(dict(content_texts(content(images=[{"name": "待确认", "url": None, "source": "来源待确认"}])))))
        self.assertEqual(result["text_check"]["status"], "passed")

    def test_new_content_invalidates_old_check_and_binds_digest_and_version(self):
        status, first = self.request()
        self.assertEqual(status, 200)
        edited = content("屏幕尺寸：99 英寸。")
        self.assertFalse(self.repo.get_final_checks(self.task["task_id"], content=edited)[0]["valid"])
        status, second = self.request(edited)
        self.assertEqual(status, 200)
        checks = self.repo.get_final_checks(self.task["task_id"])
        self.assertFalse(checks[0]["valid"])
        self.assertTrue(checks[1]["valid"])
        self.assertEqual(checks[1]["content_version"], 2)
        self.assertNotEqual(checks[0]["content_digest"], checks[1]["content_digest"])
        self.assertEqual(second["data"]["final_check"]["text_check"]["status"], "blocked")
        checks[1]["text_check"]["status"] = "passed"
        self.assertEqual(self.repo.get_final_checks(self.task["task_id"])[1]["text_check"]["status"], "blocked")

    def test_failed_edited_check_does_not_leave_old_text_approved(self):
        self.request()
        status, failed = self.request(content(additional_text=["修改后的文字"]), service=self.service(ReviewFixture(error=RuntimeError("PRIVATE_SENTINEL"))))
        self.assertEqual(status, 502)
        self.assertNotIn("PRIVATE_SENTINEL", str(failed))
        self.assertTrue(failed["data"]["task"]["fact_records"])
        self.assertFalse(self.repo.get_final_checks(self.task["task_id"])[0]["valid"])
        self.assertEqual(self.repo.get_current_strategy(self.task["task_id"])["confirmation_status"], "confirmed")

    def test_model_timeout_is_safe_diagnosed_failure(self):
        model = ReviewFixture(error=LLMClientError("LLM request timed out", category="timeout"))
        status, result = self.request(service=self.service(model))
        self.assertEqual(status, 502)
        self.assertEqual(result["error"]["code"], "FINAL_CHECK_REQUEST_TIMEOUT")
        self.assertEqual(result["data"]["diagnostics"]["stages"][0]["failure_type"], "timeout")
        self.assertEqual(self.repo.get_final_checks(self.task["task_id"]), [])

    def test_fact_checker_failure_does_not_pass_or_overwrite(self):
        class Broken:
            def check(self, *args):
                raise RuntimeError("Authorization PRIVATE_SENTINEL")
        status, result = self.request(service=self.service(checker=Broken()))
        self.assertEqual(status, 502)
        self.assertEqual(result["error"]["code"], "FINAL_FACT_CHECK_FAILED")
        self.assertNotIn("PRIVATE_SENTINEL", str(result))

    def test_invalid_result_binding_cannot_be_saved(self):
        class Unbound:
            def check(inner, *args):
                result = self.service().check(*args)
                result["content_digest"] = "forged"
                return result
        status, result = self.request(service=Unbound())
        self.assertEqual(status, 502)
        self.assertEqual(result["error"]["code"], "INVALID_FINAL_CHECK_RESULT")

    def test_stale_result_after_edit_is_rejected_and_model_does_not_hold_store_lock(self):
        def callback():
            current = self.repo.get(self.task["task_id"])
            errors = []
            def edit():
                try:
                    self.repo.update(current["task_id"], current["revision"], {"updates": {"audience": "研究生"}})
                except Exception as error:
                    errors.append(error)
            thread = threading.Thread(target=edit)
            thread.start()
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive(), "model request held the task lock")
            self.assertEqual(errors, [])
        status, result = self.request(service=self.service(ReviewFixture(callback=callback)))
        self.assertEqual(status, 409)
        self.assertEqual(result["error"]["code"], "VERSION_CONFLICT")
        self.assertEqual(self.repo.get_final_checks(self.task["task_id"]), [])

    def test_failed_model_after_concurrent_change_returns_version_conflict(self):
        def callback():
            current = self.repo.get(self.task["task_id"])
            self.repo.update(current["task_id"], current["revision"], {"clear_fields": ["product_query"]})
        status, result = self.request(service=self.service(ReviewFixture(callback=callback, error=RuntimeError("PRIVATE"))))
        self.assertEqual(status, 409)
        self.assertEqual(result["error"]["code"], "VERSION_CONFLICT")

    def test_stale_task_strategy_and_cross_task_references_are_rejected(self):
        self.request()
        status, result = self.request(task=self.task)
        self.assertEqual(status, 409)
        self.assertEqual(result["error"]["code"], "VERSION_CONFLICT")
        wrong = {**self.strategy, "strategy_version": 999}
        self.assertEqual(self.request(strategy=wrong)[0], 409)
        other, _ = confirmed(self.repo)
        self.assertEqual(self.request(task=other, strategy=self.strategy)[0], 409)

    def test_requirement_and_product_edit_invalidate_previous_final_result(self):
        for field, value in (("platform", "门店朋友圈"), ("product_query", "OTHER_MODEL")):
            with self.subTest(field=field):
                repo = TaskRepository()
                with patch.object(workflow, "REPOSITORY", repo):
                    task, strategy = confirmed(repo)
                    status, result = self.request(task=task, strategy=strategy)
                    self.assertEqual(status, 200)
                    current = repo.get(task["task_id"])
                    repo.update(task["task_id"], current["revision"], {"updates": {field: value}})
                    self.assertFalse(repo.get_final_checks(task["task_id"])[0]["valid"])

    def test_contract_rejects_hidden_fields_and_invalid_images_before_model_call(self):
        for draft in (content(arbitrary="not reviewed"), content(images=[{"unknown_text": "虚假参数"}]),
                      content(images=[{"status": []}]), content(body="", plain_text="", title="")):
            with self.subTest(draft=draft):
                with self.assertRaises(ContractValidationError):
                    validate_final_content(draft)


class ConfirmationMeaningTests(unittest.TestCase):
    def context(self):
        repo = TaskRepository()
        task, strategy = confirmed(repo)
        task, context, facts = repo.strategy_snapshot(task["task_id"], task["revision"])
        return repo, task, strategy, context, facts

    def test_verified_model_reminder_is_adjusted_but_limits_are_retained(self):
        _, task, draft, context, facts = self.context()
        text = "发布前确认引用记录与指定型号的对应关系"
        draft["pending_confirmations"].append(text)
        result, blockers = review_confirmation_gaps(task, draft, facts, context)
        self.assertEqual(blockers, [])
        self.assertNotIn(text, result["pending_confirmations"])
        self.assertIn("已核对", "".join(result["risk_notes"]))
        self.assertIn("不代表实时", "".join(result["risk_notes"]))
        self.assertIn(text, draft["pending_confirmations"])

    def test_unverified_association_and_configuration_gap_still_block_confirmation(self):
        _, task, draft, context, facts = self.context()
        context["evidence_documents"] = []
        draft["pending_confirmations"] = ["发布前确认引用记录与指定型号的对应关系"]
        self.assertTrue(review_confirmation_gaps(task, draft, facts, context)[1])
        _, task, draft, context, facts = self.context()
        draft["pending_confirmations"] = ["发布前确认配置参数是否适用"]
        self.assertTrue(review_confirmation_gaps(task, draft, facts, context)[1])

    def test_source_display_preference_is_nonblocking(self):
        _, task, draft, context, facts = self.context()
        draft["pending_confirmations"] = ["发布前确认来源展示格式"]
        self.assertEqual(review_confirmation_gaps(task, draft, facts, context)[1], [])


if __name__ == "__main__":
    unittest.main()
