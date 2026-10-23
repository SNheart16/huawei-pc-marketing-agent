"""Offline strategy workflow checks. All products/evidence are synthetic fixtures."""

import copy
import json
import os
import threading
import unittest
from unittest.mock import patch

from src.fact_checker import FactChecker
from src.llm_client import LLMClientError
from src.strategy_service import (
    StrategyService, StrategyServiceError, _generation_payload, _public_texts,
    _request_size, strategy_timeout_seconds,
)
import src.workflow_service as workflow
from src.workflow_service import TaskRepository, WorkflowError


MODEL = "SYNTHETIC_TEST_MODEL"
CLAIM = "屏幕尺寸：13.2 英寸。"
SOURCE = {"mode": "local", "name": "fixture", "live": False, "status": "ok", "message": "synthetic"}


def seed(repo, *, checked=True, **changes):
    task = repo.create({
        "source": "direct", "user_input": "仅用于离线策略测试",
        "product_query": MODEL, "audience": "大学生", "platform": "小红书",
        "goal": "介绍有依据的信息", "scene": "开学季", "constraints": ["不写价格"], **changes,
    })
    task = repo.begin_research(task["task_id"], task["revision"])
    records = [{
        "fact_id": fid, "product_model": MODEL, "claim": text, "evidence_text": text,
        "source_ref": f"fixtures/{fid}.md", "source_type": "other", "status": "retrieved",
        "retrieved_at": "2026-10-22T00:00:00Z", "valid_until": None,
    } for fid, text in (("F1", CLAIM), ("F2", "处理器：测试 CPU A，仅适用 Windows 版本。"))]
    task = repo.complete_research(task["task_id"], task["revision"], records,
        knowledge_source=SOURCE, evidence_documents=[
            {"source_ref": r["source_ref"], "product_model": MODEL, "content": r["evidence_text"]}
            for r in records])
    if checked:
        task, context = repo.fact_check_snapshot(task["task_id"], task["revision"])
        # Negative tests deliberately do not poison the independently supported F1.
        claims = [{"claim": CLAIM, "fact_references": ["F1"]},
                  {"claim": "屏幕尺寸：99 英寸。", "fact_references": ["F1"]},
                  {"claim": "今日优惠 1000 元。", "fact_references": []}]
        task, _ = repo.complete_fact_check(task, context, claims, FactChecker().check(task, claims, context))
    return task


def response_for(payload):
    task, record = payload["task"], payload["eligible_fact_records"][0]
    need = "待确认的需求推断：该人群希望先了解产品信息，仍需具体人群确认。"
    draft = {
        "task_summary": f"建议围绕{task['scene']}为{task['audience']}规划内容。",
        "topic": f"建议以{task['goal']}为主题，在{task['platform']}呈现。",
        "audience": {"description": task["audience"], "basis": "当前用户明确提供", "basis_type": "user_provided"},
        "audience_need": need, "core_message": record["claim"],
        "content_angle": "建议以用户的问题引出信息卡。", "content_format": f"{task['platform']}信息卡",
        "content_outline": [{"section": "开场", "purpose": "建议先提出一个问题", "fact_references": []},
                            {"section": "信息卡", "purpose": record["claim"], "fact_references": [record["fact_id"]]}],
        "cta": "", "fact_references": [record["fact_id"]], "assumptions": [need],
        "pending_confirmations": ["发布前确认受众与具体表达偏好"],
        "risk_notes": ["本地副本的有效性需要另行确认，不代表实时信息。"],
    }
    return {"strategy": draft, "fact_claims": [
        {"field_path": path, "claim": record["claim"], "fact_references": [record["fact_id"]]}
        for path in ("core_message", "content_outline[1].purpose")
    ]}


class ModelFixture:
    def __init__(self, mutate=None, audit_mutate=None, callback=None, fail_stage=None):
        self.mutate, self.audit_mutate, self.callback, self.fail_stage = mutate, audit_mutate, callback, fail_stage
        self.calls = []
        self.generated = 0

    def generate_json(self, prompt, payload):
        self.calls.append(copy.deepcopy(payload))
        if "fields" in payload:
            if self.fail_stage == "audit":
                raise RuntimeError("Authorization PRIVATE_SENTINEL")
            fields = []
            for field in payload["fields"]:
                claims = [entry["claim"] for entry in payload["declared_fact_claims"]
                          if entry["field_path"] == field["field_path"]]
                kind = "factual" if claims else (
                    "assumption" if field["field_path"].startswith(("audience_need", "assumptions[")) else "planning")
                fields.append({**field, "kind": kind, "claims": claims})
            review = {"fields": fields}
            if self.audit_mutate:
                self.audit_mutate(review, payload)
            return review
        if self.fail_stage == "generate":
            raise RuntimeError("Authorization PRIVATE_SENTINEL")
        self.generated += 1
        if self.callback:
            self.callback()
        result = response_for(payload)
        if self.mutate:
            self.mutate(result, self.generated)
        return result


class SemanticFixture:
    """Evidence-bound semantic replies; never calls a real model."""

    def __init__(self):
        self.calls = []

    def generate_json(self, prompt, payload):
        self.calls.append(copy.deepcopy(payload))
        return {"checks": [{"index": item["index"], "status": "supported", "evidence": [
            {"fact_id": record["fact_id"], "quote": record["evidence_text"]}
            for record in item["records"]
        ]} for item in payload["checks"]]}


class StrategyServiceTests(unittest.TestCase):
    def setUp(self):
        self.repo = TaskRepository()
        for name, value in (("REPOSITORY", self.repo), ("STRATEGY_SERVICE", None), ("FACT_CHECKER", FactChecker())):
            item = patch.object(workflow, name, value)
            item.start()
            self.addCleanup(item.stop)

    def generate(self, task=None, model=None, checker=None):
        task = task or seed(self.repo)
        task, context, eligible = self.repo.strategy_snapshot(task["task_id"], task["revision"])
        model = model or ModelFixture()
        assessment = StrategyService(model, checker).generate(task, eligible, context)
        return task, context, assessment, model

    def save(self, task=None):
        task, context, assessment, _ = self.generate(task)
        return self.repo.add_strategy(task["task_id"], task["revision"], assessment["draft"], assessment=assessment, context=context)

    def test_supported_only_generation_empty_cta_and_source_limits(self):
        task, context, result, model = self.generate()
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["draft"]["cta"], "")
        self.assertEqual(result["draft"]["fact_references"], ["F1"])
        self.assertEqual(result["fact_check"]["counts"]["supported"], 2)
        generation = model.calls[0]
        self.assertEqual([r["fact_id"] for r in generation["eligible_fact_records"]], ["F1"])
        self.assertNotIn("evidence_documents", generation)
        self.assertFalse(generation["source_limits"]["knowledge_source"]["live"])
        self.assertTrue(any("other" in warning for warning in generation["source_limits"]["warnings"]))
        self.assertTrue(any("有效性未知" in warning for warning in generation["source_limits"]["warnings"]))

    def test_generation_request_excludes_history_unchecked_records_and_source_message(self):
        task = seed(self.repo)
        task, context, eligible = self.repo.strategy_snapshot(task["task_id"], task["revision"])
        task["conversation_history"] = ["PRIVATE_UNRELATED_HISTORY"]
        task["user_input"] = "PRIVATE_ORIGINAL_TEXT"
        context["knowledge_source"]["message"] = "PRIVATE_SOURCE_MESSAGE"
        context["test_example"] = "PRIVATE_EXAMPLE"
        payload = _generation_payload(task, eligible, context)
        encoded = json.dumps(payload, ensure_ascii=False)
        self.assertEqual(set(payload), {"task", "source_limits", "eligible_fact_records"})
        self.assertEqual([record["fact_id"] for record in payload["eligible_fact_records"]], ["F1"])
        for value in ("PRIVATE_UNRELATED_HISTORY", "PRIVATE_ORIGINAL_TEXT", "PRIVATE_SOURCE_MESSAGE",
                      "PRIVATE_EXAMPLE", "F2", "evidence_documents", "retrieved_fact_records"):
            self.assertNotIn(value, encoded)

    def test_generation_request_preserves_fact_qualifiers_and_provenance(self):
        task = seed(self.repo)
        task, context, _ = self.repo.strategy_snapshot(task["task_id"], task["revision"])
        record = task["fact_records"][1]
        record["valid_until"] = "2026-12-31T23:59:59Z"
        payload = _generation_payload(task, [record], context)
        projected = payload["eligible_fact_records"][0]
        for field in ("claim", "evidence_text", "product_model", "source_ref", "source_type", "valid_until"):
            self.assertEqual(projected[field], record[field])
        self.assertIn("仅适用 Windows 版本", projected["evidence_text"])

    def test_request_metrics_match_actual_serialized_messages_without_content(self):
        _, _, result, model = self.generate()
        initial = result["diagnostics"]["stages"][1]
        from src.strategy_service import _prompt
        metrics = _request_size(_prompt(), model.calls[0])
        self.assertEqual(initial["request_size"], metrics)
        self.assertEqual(metrics["payload_chars"], len(json.dumps(model.calls[0], ensure_ascii=False, allow_nan=False)))
        self.assertEqual(metrics["system_prompt_chars"], len(_prompt() + "\nReturn a JSON object."))
        self.assertEqual(metrics["fact_count"], 1)
        self.assertEqual(metrics["history_turn_count"], 0)
        self.assertTrue(all(type(value) is int for value in metrics.values()))

    def test_timeout_is_runtime_configured_and_only_passed_to_strategy_client(self):
        task = seed(self.repo)
        task, context, eligible = self.repo.strategy_snapshot(task["task_id"], task["revision"])
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(strategy_timeout_seconds(), 120)
            with patch("src.strategy_service.LLMClient", return_value=ModelFixture()) as constructor:
                StrategyService(fact_checker=FactChecker()).generate(task, eligible, context)
                constructor.assert_called_once_with(timeout=120)
            os.environ["STRATEGY_LLM_TIMEOUT_SECONDS"] = "83"
            with patch("src.strategy_service.LLMClient", return_value=ModelFixture()) as constructor:
                StrategyService(fact_checker=FactChecker()).generate(task, eligible, context)
                constructor.assert_called_once_with(timeout=83)
            from src.llm_client import LLMClient
            with patch("src.llm_client.build_opener"):
                other_client = LLMClient(api_key="synthetic", base_url="https://example.invalid", model="fixture")
            self.assertEqual(other_client.timeout, 45)

    def test_invalid_timeout_is_safe_configuration_failure_before_any_model_request(self):
        for value in ("0", "-1", "nan", "inf", "PRIVATE_SENTINEL"):
            model = ModelFixture()
            with self.subTest(value=value), patch.dict(os.environ, {"STRATEGY_LLM_TIMEOUT_SECONDS": value}):
                with self.assertRaises(StrategyServiceError) as error:
                    self.generate(model=model)
                self.assertEqual(error.exception.code, "STRATEGY_CONFIGURATION_ERROR")
                self.assertEqual(error.exception.diagnostics["model_call_count"], 0)
                self.assertEqual(error.exception.diagnostics["stages"][-1]["stage"], "setup")
                self.assertNotIn("PRIVATE_SENTINEL", str(error.exception))
                self.assertEqual(model.calls, [])

    def test_no_eligible_facts_never_calls_model(self):
        model = ModelFixture()
        task = seed(self.repo, checked=False)
        with self.assertRaises(WorkflowError) as error:
            self.repo.strategy_snapshot(task["task_id"], task["revision"])
        self.assertEqual(error.exception.code, "NO_VERIFIED_FACTS")
        with self.assertRaises(StrategyServiceError):
            StrategyService(model).generate(task, [], {})
        self.assertEqual(model.calls, [])

    def test_forged_or_unchecked_reference_is_blocked_after_one_repair(self):
        for ref in ("forged", "F2"):
            def mutate(raw, attempt):
                raw["strategy"]["fact_references"] = [ref]
                for entry in raw["fact_claims"]:
                    entry["fact_references"] = [ref]
            _, _, result, model = self.generate(model=ModelFixture(mutate=mutate))
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(model.generated, 2)
            self.assertTrue(result["blocking_items"])

    def test_invalid_strategy_contract_returns_specific_safe_blocker(self):
        def mutate(raw, attempt):
            raw["strategy"].pop("topic")
        _, _, result, model = self.generate(model=ModelFixture(mutate))
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(model.generated, 2)
        self.assertIn("StrategyDraft 字段不符合契约", result["blocking_items"][0]["reason"])

    def test_non_verbatim_fact_mapping_returns_specific_safe_blocker(self):
        def mutate(raw, attempt):
            raw["fact_claims"][0]["claim"] = "对这条产品事实做了概括改写。"
        _, _, result, model = self.generate(model=ModelFixture(mutate))
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(model.generated, 2)
        self.assertIn("连续原文", result["blocking_items"][0]["reason"])

    def test_invalid_fact_mapping_path_is_blocked_with_specific_reason(self):
        for path in ("strategy.core_message", "content_outline.1.purpose", "content_outline[99].purpose"):
            with self.subTest(path=path):
                def mutate(raw, attempt):
                    raw["fact_claims"][0]["field_path"] = path
                _, _, result, model = self.generate(model=ModelFixture(mutate))
                self.assertEqual(result["status"], "blocked")
                self.assertEqual(model.generated, 2)
                self.assertIn("field_path", result["blocking_items"][0]["reason"])

    def test_new_parameter_and_dropped_condition_cannot_pass(self):
        for claim in ("屏幕尺寸：99 英寸。", "处理器：测试 CPU A。", "MateBook X Pro 2021 屏幕尺寸：13.2 英寸。"):
            def mutate(raw, attempt):
                raw["strategy"]["core_message"] = claim
                raw["fact_claims"][0]["claim"] = claim
            _, _, result, _ = self.generate(model=ModelFixture(mutate=mutate))
            self.assertEqual(result["status"], "blocked")

    def test_every_public_field_is_checked_not_only_references(self):
        for field in ("topic", "cta", "task_summary", "content_angle"):
            def mutate(raw, attempt):
                raw["strategy"][field] = "屏幕尺寸：99 英寸。"
            _, _, result, _ = self.generate(model=ModelFixture(mutate=mutate))
            self.assertEqual(result["status"], "blocked")
            self.assertTrue(any(item["field_path"] == field for item in result["blocking_items"]))

    def test_planning_layout_and_constraints_do_not_require_product_evidence(self):
        examples = (
            "建议采用三张图呈现。",
            "不要写证据未支持的参数。",
            "建议采用屏幕参数信息卡呈现。",
            "建议采用“开学季学习装备参数核查”的内容角度，围绕可核查信息展开整理，不延伸推断性能体验或购买意愿。",
            "建议采用小红书参数信息卡与场景化分段图文，按“学习场景需求待确认—配置信息整理—信息边界说明”的顺序呈现。",
            "建议仅呈现已核查的信息，不补充价格、优惠、个人体验、排名或证据未支持的参数。",
        )
        for text in examples:
            with self.subTest(text=text):
                def mutate(raw, attempt):
                    raw["strategy"]["content_angle"] = text
                    raw["strategy"]["content_format"] = text
                    raw["strategy"]["content_outline"][0]["purpose"] = text
                def audit(review, payload):
                    for item in review["fields"]:
                        if item["text"] == text:
                            item["kind"] = "constraint" if "不要写" in text or "不补充" in text else "planning"
                _, _, result, model = self.generate(model=ModelFixture(mutate, audit))
                self.assertEqual(result["status"], "passed")
                self.assertEqual(model.generated, 1)
                self.assertEqual(result["fact_check"]["counts"]["supported"], 2)
                # No field is skipped: each still went through the independent audit.
                reviewed = {item["field_path"] for item in result["coverage_review"]["fields"]}
                self.assertTrue({"content_angle", "content_format", "content_outline[0].purpose"} <= reviewed)

    def test_suggestion_and_layout_cannot_hide_unmapped_product_assertions(self):
        examples = (
            "建议突出电脑支持全天续航。",
            "采用双栏排版，突出其配备某处理器。",
            "建议以今日到手价 4999 元为主题。",
            "建议突出屏幕尺寸：99 英寸。",
        )
        for text in examples:
            with self.subTest(text=text):
                def mutate(raw, attempt):
                    raw["strategy"]["content_angle"] = text
                _, _, result, _ = self.generate(model=ModelFixture(mutate))
                self.assertEqual(result["status"], "blocked")
                self.assertTrue(any(item["field_path"] == "content_angle" for item in result["blocking_items"]))

    def test_embedded_fact_clause_is_checked_without_the_layout_prefix(self):
        def mutate(raw, attempt):
            raw["strategy"]["content_format"] = "采用双栏排版，信息卡写明：" + CLAIM
            raw["fact_claims"].append({"field_path": "content_format", "claim": CLAIM, "fact_references": ["F1"]})
        _, _, result, _ = self.generate(model=ModelFixture(mutate))
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["fact_check"]["counts"]["supported"], 3)
        embedded = next(item for item in result["fact_claims"] if item["field_path"] == "content_format")
        self.assertEqual(embedded["claim"], CLAIM)

    def test_mapped_unsupported_facts_in_suggestions_still_fail_evidence_checks(self):
        for claim in ("电脑支持全天续航。", "处理器：测试 CPU B。", "今日到手价 4999 元。",
                      "MateBook X Pro 2021 屏幕尺寸：13.2 英寸。"):
            with self.subTest(claim=claim):
                def mutate(raw, attempt):
                    raw["strategy"]["content_angle"] = "建议突出：" + claim
                    raw["fact_claims"].append({"field_path": "content_angle", "claim": claim, "fact_references": ["F1"]})
                _, _, result, _ = self.generate(model=ModelFixture(mutate), checker=FactChecker(SemanticFixture()))
                self.assertEqual(result["status"], "blocked")
                self.assertTrue(any(item["field_path"] == "content_angle" for item in result["blocking_items"]))

    def test_faithful_rewrite_uses_existing_semantic_checker_not_verbatim_evidence(self):
        rewrite = "屏幕尺寸为 13.2 英寸。"
        def mutate(raw, attempt):
            raw["strategy"]["core_message"] = rewrite
            raw["strategy"]["content_outline"][1]["purpose"] = rewrite
            for item in raw["fact_claims"]:
                item["claim"] = rewrite
        semantic = SemanticFixture()
        _, _, result, _ = self.generate(model=ModelFixture(mutate), checker=FactChecker(semantic))
        self.assertNotEqual(rewrite, CLAIM)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(len(semantic.calls), 1)
        self.assertEqual(result["fact_check"]["counts"]["supported"], 2)
        self.assertTrue(all(item["evidence"] == [CLAIM] for item in result["fact_check"]["results"]))

    def test_uncertain_statement_classification_explicitly_requires_confirmation(self):
        def audit(review, payload):
            next(item for item in review["fields"] if item["field_path"] == "content_angle")["kind"] = "uncertain"
        _, _, result, _ = self.generate(model=ModelFixture(audit_mutate=audit))
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(any(item["field_path"] == "content_angle" and item["status"] == "needs_confirmation"
                            for item in result["blocking_items"]))

    def test_independent_audit_finds_assertion_without_known_keywords(self):
        def mutate(raw, attempt):
            raw["strategy"]["topic"] = "附近学生都会购买。"
        def audit(review, payload):
            for item in review["fields"]:
                if item["field_path"] == "topic":
                    item.update(kind="factual", claims=[item["text"]])
        _, _, result, model = self.generate(model=ModelFixture(mutate, audit))
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(model.generated, 2)
        self.assertTrue(any("独立审查" in r["reason"] for r in result["blocking_items"]))

    def test_missing_or_modified_audit_fields_rejects_review(self):
        for change in (lambda review, _: review["fields"].pop(),
                       lambda review, _: review["fields"][0].update(text="changed")):
            with self.assertRaises(StrategyServiceError) as error:
                self.generate(model=ModelFixture(audit_mutate=change))
            self.assertEqual(error.exception.code, "STRATEGY_CHECK_INVALID")

    def test_audience_need_must_remain_in_assumptions(self):
        def mutate(raw, attempt):
            raw["strategy"]["assumptions"] = []
        _, _, result, _ = self.generate(model=ModelFixture(mutate))
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(any(i["field_path"] == "audience_need" for i in result["blocking_items"]))

    def test_faithful_scope_kept_for_qualified_fact(self):
        task = seed(self.repo)
        task, context = self.repo.fact_check_snapshot(task["task_id"], task["revision"])
        record = task["fact_records"][1]
        claims = [{"claim": record["claim"], "fact_references": [record["fact_id"]]}]
        task, _ = self.repo.complete_fact_check(task, context, claims, FactChecker().check(task, claims, context))
        task, context, eligible = self.repo.strategy_snapshot(task["task_id"], task["revision"])
        eligible = [r for r in eligible if r["fact_id"] == "F2"]
        def mutate(raw, attempt):
            raw["strategy"]["core_message"] = "处理器：测试 CPU A。"
            raw["fact_claims"][0]["claim"] = raw["strategy"]["core_message"]
        result = StrategyService(ModelFixture(mutate)).generate(task, eligible, context)
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(any("限定" in i["reason"] for i in result["blocking_items"]))

    def test_one_targeted_repair_then_full_recheck(self):
        def mutate(raw, attempt):
            if attempt == 1:
                raw["strategy"]["cta"] = "屏幕尺寸：99 英寸。"
        _, _, result, model = self.generate(model=ModelFixture(mutate))
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["attempts"], 2)
        self.assertIn("blocking_items", model.calls[1])
        self.assertEqual(model.generated, 2)

    def test_platform_and_goal_affect_generated_strategy(self):
        first = self.generate(seed(self.repo, platform="小红书", goal="介绍信息"))[2]["draft"]
        second = self.generate(seed(self.repo, platform="门店朋友圈", goal="解释选择依据"))[2]["draft"]
        self.assertNotEqual(first["topic"], second["topic"])
        self.assertNotEqual(first["content_format"], second["content_format"])

    def test_model_and_audit_failure_are_safe_without_fake_fallback(self):
        for stage, diagnostic_stage in (("generate", "initial_generation"), ("audit", "strategy_audit")):
            with self.assertRaises(StrategyServiceError) as error:
                self.generate(model=ModelFixture(fail_stage=stage))
            self.assertEqual(error.exception.code, "STRATEGY_INTERNAL_ERROR")
            self.assertEqual(error.exception.http_status, 500)
            diagnostic = error.exception.diagnostics
            self.assertEqual(diagnostic["stages"][-1]["stage"], diagnostic_stage)
            self.assertEqual(diagnostic["stages"][-1]["failure_type"], "internal")
            self.assertNotIn("PRIVATE_SENTINEL", json.dumps(diagnostic))
            self.assertNotIn("PRIVATE_SENTINEL", str(error.exception))

    def test_model_http_status_is_reported_without_response_or_credentials(self):
        class HttpFailure:
            def generate_json(self, *args):
                raise LLMClientError("unsafe detail PRIVATE_SENTINEL", 503)
        with self.assertRaises(StrategyServiceError) as error:
            self.generate(model=HttpFailure())
        self.assertEqual(error.exception.code, "STRATEGY_UPSTREAM_HTTP_ERROR")
        self.assertIn("HTTP 503", str(error.exception))
        self.assertNotIn("PRIVATE_SENTINEL", str(error.exception))

    def test_known_llm_timeout_is_classified_but_unknown_error_is_hidden(self):
        class Failure:
            def __init__(self, error):
                self.error = error
            def generate_json(self, *args):
                raise self.error
        for model, expected in (
            (Failure(LLMClientError("LLM request timed out")), "请求超时"),
            (Failure(LLMClientError("PRIVATE_SENTINEL Authorization")), "PRIVATE_SENTINEL"),
        ):
            with self.assertRaises(StrategyServiceError) as error:
                self.generate(model=model)
            if expected == "PRIVATE_SENTINEL":
                self.assertNotIn(expected, str(error.exception))
            else:
                self.assertIn(expected, str(error.exception))

    def test_checker_exception_and_unbound_success_are_rejected(self):
        class FailedChecker:
            def check(self, *args):
                raise RuntimeError("PRIVATE_SENTINEL")
        with self.assertRaises(StrategyServiceError) as error:
            self.generate(checker=FailedChecker())
        self.assertEqual(error.exception.code, "STRATEGY_INTERNAL_ERROR")
        self.assertEqual(error.exception.diagnostics["stages"][-1]["stage"], "fact_check")
        class ForgedChecker:
            def check(self, task, claims, context):
                result = FactChecker().check(task, claims, context)
                result["results"][0]["source_refs"] = ["invented.md"]
                return result
        with self.assertRaises(StrategyServiceError) as error:
            self.generate(checker=ForgedChecker())
        self.assertEqual(error.exception.code, "STRATEGY_CHECK_INVALID")

    def test_distinct_generation_failures_reach_http_diagnostics(self):
        cases = [("connection", "STRATEGY_CONNECTION_FAILED"), ("timeout", "STRATEGY_REQUEST_TIMEOUT"),
                 ("json_parse", "STRATEGY_JSON_INVALID"), ("response_schema", "STRATEGY_RESPONSE_INVALID")]
        for kind, code in cases:
            with self.subTest(kind=kind):
                class Failure:
                    def generate_json(self, *args):
                        raise LLMClientError("PRIVATE_SENTINEL", category=kind)
                task = seed(self.repo)
                workflow.set_strategy_service(StrategyService(Failure()))
                status, result = workflow.dispatch("/api/strategy/generate", {"task_id": task["task_id"], "expected_revision": task["revision"]})
                self.assertEqual(status, 502)
                self.assertEqual(result["error"]["code"], code)
                trace = result["data"]["diagnostics"]
                self.assertEqual(trace["stages"][-1]["failure_type"], kind)
                self.assertEqual(trace["model_call_count"], 1)
                self.assertNotIn("PRIVATE_SENTINEL", json.dumps(result))
                self.assertIsNone(self.repo.get_current_strategy(task["task_id"]))

    def test_fact_block_is_not_a_transport_error_and_has_bounded_stage_counts(self):
        def mutate(raw, attempt):
            raw["strategy"]["cta"] = "屏幕尺寸：99 英寸。"
        task = seed(self.repo)
        workflow.set_strategy_service(StrategyService(ModelFixture(mutate)))
        status, result = workflow.dispatch("/api/strategy/generate", {"task_id": task["task_id"], "expected_revision": task["revision"]})
        self.assertEqual(status, 422)
        self.assertEqual(result["error"]["code"], "STRATEGY_FACTS_UNSUPPORTED")
        self.assertEqual(result["data"]["attempts"], 2)
        trace = result["data"]["diagnostics"]
        self.assertEqual(trace["model_call_count"], 2)
        self.assertEqual(trace["stages"][-1]["failure_type"], "fact_blocked")
        self.assertIn("repair", [s["stage"] for s in trace["stages"]])

    def test_invalid_strategy_structure_is_separate_from_fact_rejection(self):
        def mutate(raw, attempt):
            raw["strategy"].pop("topic")
        task = seed(self.repo)
        workflow.set_strategy_service(StrategyService(ModelFixture(mutate)))
        status, result = workflow.dispatch("/api/strategy/generate", {"task_id": task["task_id"], "expected_revision": task["revision"]})
        self.assertEqual(status, 422)
        self.assertEqual(result["error"]["code"], "STRATEGY_RESPONSE_INVALID")
        self.assertEqual(result["data"]["diagnostics"]["stages"][-1]["failure_type"], "response_schema")

    def test_semantic_failure_keeps_fact_check_stage_and_safe_category(self):
        class FailedChecker:
            def check(self, *args):
                return {"results": [{}, {}], "errors": [{"code": "FACT_CHECK_REQUEST_TIMEOUT"}],
                        "diagnostics": {"status": "failed", "failure_type": "timeout", "exception_types": ["TimeoutError"],
                                        "model_call_count": 1, "upstream_request_count": 1, "upstream_requests": []}}
        with self.assertRaises(StrategyServiceError) as error:
            self.generate(checker=FailedChecker())
        self.assertEqual(error.exception.code, "STRATEGY_REQUEST_TIMEOUT")
        trace = error.exception.diagnostics
        self.assertEqual(trace["stages"][-1]["stage"], "fact_check")
        self.assertEqual(trace["model_call_count"], 3)

    def test_server_owns_strategy_identity_and_confirmation(self):
        def mutate(raw, attempt):
            raw["strategy"].update(strategy_id="model-picked", confirmation_status="confirmed")
        _, _, result, _ = self.generate(model=ModelFixture(mutate))
        self.assertEqual(result["status"], "blocked")
        task, strategy = self.save()
        self.assertTrue(strategy["strategy_id"].startswith("strategy-"))
        self.assertEqual(strategy["confirmation_status"], "pending")
        task, confirmed = self.repo.confirm_strategy(task["task_id"], task["revision"], strategy["strategy_id"], strategy["strategy_version"])
        self.assertEqual(task["workflow_status"], "strategy_confirmed")
        self.assertEqual(confirmed["confirmed_at_task_revision"], task["revision"])

    def test_direct_unscreened_draft_cannot_be_saved(self):
        task, _, result, _ = self.generate()
        with self.assertRaises(WorkflowError) as error:
            self.repo.add_strategy(task["task_id"], task["revision"], result["draft"])
        self.assertEqual(error.exception.code, "STRATEGY_CHECK_REQUIRED")

    def test_confirmation_is_bound_to_all_ids_and_versions(self):
        task, strategy = self.save()
        for sid, version in (("invented", 1), (strategy["strategy_id"], 2)):
            with self.assertRaises(WorkflowError):
                self.repo.confirm_strategy(task["task_id"], task["revision"], sid, version)
        with self.assertRaises(WorkflowError) as error:
            self.repo.confirm_strategy(task["task_id"], task["revision"] - 1, strategy["strategy_id"], 1)
        self.assertEqual(error.exception.code, "VERSION_CONFLICT")

    def test_requirement_changes_invalidate_confirmation_but_keep_product_checks(self):
        for field, value in (("audience", "职场新人"), ("platform", "门店朋友圈"), ("goal", "介绍使用条件")):
            task, strategy = self.save()
            task, confirmed = self.repo.confirm_strategy(task["task_id"], task["revision"], strategy["strategy_id"], 1)
            task = self.repo.update(task["task_id"], task["revision"], {"updates": {field: value}})
            self.assertIsNone(task["current_strategy_id"])
            self.assertEqual(task["fact_records"][0]["status"], "supported")
            self.assertTrue(self.repo.get_fact_checks(task["task_id"])[0]["valid"])
            with self.assertRaises(WorkflowError):
                self.repo.creative_handoff(task["task_id"], task["revision"], confirmed["strategy_id"], 1)

    def test_product_change_clears_facts_and_invalidates_all_checks(self):
        task, strategy = self.save()
        task = self.repo.update(task["task_id"], task["revision"], {"clear_fields": ["product_query"]})
        self.assertEqual(task["fact_records"], [])
        self.assertFalse(self.repo.get_fact_checks(task["task_id"])[0]["valid"])
        self.assertFalse(self.repo.get_strategy_check(task["task_id"], strategy["strategy_id"])["valid"])

    def test_new_strategy_requires_reconfirmation_and_history_is_immutable(self):
        task, first = self.save()
        task, confirmed = self.repo.confirm_strategy(task["task_id"], task["revision"], first["strategy_id"], 1)
        task, second = self.save(task)
        self.assertEqual(second["strategy_version"], 2)
        self.assertEqual(second["confirmation_status"], "pending")
        history = self.repo.get_strategy_history(task["task_id"])
        self.assertTrue(any(s == confirmed for s in history))
        history[0]["core_message"] = "external mutation"
        self.assertEqual(self.repo.get_strategy_history(task["task_id"])[0]["core_message"], CLAIM)
        with self.assertRaises(WorkflowError):
            self.repo.confirm_strategy(task["task_id"], task["revision"], first["strategy_id"], 1)

    def test_handoff_contains_only_adopted_checked_facts_and_unknown_images(self):
        task, strategy = self.save()
        with self.assertRaises(WorkflowError):
            self.repo.creative_handoff(task["task_id"], task["revision"], strategy["strategy_id"], 1)
        task, _ = self.repo.confirm_strategy(task["task_id"], task["revision"], strategy["strategy_id"], 1)
        handoff = self.repo.creative_handoff(task["task_id"], task["revision"], strategy["strategy_id"], 1)
        self.assertEqual([r["fact_id"] for r in handoff["fact_records"]], ["F1"])
        self.assertEqual(handoff["task"]["fact_records"], handoff["fact_records"])
        self.assertTrue(all(r["status"] == "supported" for batch in handoff["fact_checks"] for r in batch["results"]))
        self.assertNotIn("evidence_documents", handoff)
        self.assertEqual(handoff["image_status"], "unknown")
        self.assertEqual(handoff["images"], [])
        self.assertFalse(handoff["knowledge_source"]["live"])
        handoff["strategy"]["core_message"] = "external mutation"
        self.assertEqual(self.repo.get_current_strategy(task["task_id"])["core_message"], CLAIM)
        for version in (1.0, True, "1"):
            with self.assertRaises(WorkflowError):
                self.repo.creative_handoff(task["task_id"], task["revision"], strategy["strategy_id"], version)

    def test_other_task_cannot_confirm_or_reuse_strategy(self):
        task, strategy = self.save()
        other = seed(self.repo)
        with self.assertRaises(WorkflowError):
            self.repo.confirm_strategy(other["task_id"], other["revision"], strategy["strategy_id"], 1)
        _, context, assessment, _ = self.generate(task)
        with self.assertRaises(WorkflowError):
            self.repo.add_strategy(other["task_id"], other["revision"], assessment["draft"], assessment=assessment, context=context)

    def test_model_call_does_not_hold_repository_lock_and_stale_result_is_discarded(self):
        task = seed(self.repo)
        completed = threading.Event()
        def update():
            self.repo.update(task["task_id"], task["revision"], {"updates": {"audience": "另一受众"}})
            completed.set()
        def callback():
            thread = threading.Thread(target=update, daemon=True)
            thread.start()
            self.assertTrue(completed.wait(2), "model call held repository lock")
            thread.join(2)
        workflow.set_strategy_service(StrategyService(ModelFixture(callback=callback)))
        status, response = workflow.dispatch("/api/strategy/generate", {"task_id": task["task_id"], "expected_revision": task["revision"]})
        self.assertEqual(status, 409)
        self.assertEqual(response["error"]["code"], "VERSION_CONFLICT")
        self.assertIsNone(self.repo.get_current_strategy(task["task_id"]))

    def test_failed_model_after_concurrent_change_reports_version_conflict(self):
        task = seed(self.repo)
        class StaleFailure:
            def generate(inner, *args):
                self.repo.update(task["task_id"], task["revision"], {"clear_fields": ["product_query"]})
                raise StrategyServiceError("STRATEGY_MODEL_UNAVAILABLE", "safe failure")
        workflow.set_strategy_service(StaleFailure())
        status, response = workflow.dispatch("/api/strategy/generate", {"task_id": task["task_id"], "expected_revision": task["revision"]})
        self.assertEqual(status, 409)
        self.assertEqual(response["error"]["code"], "VERSION_CONFLICT")


if __name__ == "__main__":
    unittest.main()
