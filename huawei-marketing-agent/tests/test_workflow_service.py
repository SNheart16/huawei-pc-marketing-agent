"""Offline tests for task isolation, revisioning and explicit confirmation."""

import threading
import unittest
from unittest.mock import patch

import src.workflow_service as workflow_service
from src.fact_checker import FactChecker
from src.strategy_service import _public_texts
from src.workflow_service import TaskRepository, WorkflowError, dispatch, set_repository, set_research_service


MODEL = "Model Exact"


def task_payload(**changes):
    value = {
        "source": "direct", "user_input": "原始需求不变",
        "product_query": MODEL, "audience": "大学新生", "platform": "小红书",
        "goal": "介绍资料支持的信息", "scene": "开学季", "constraints": ["不写价格"],
    }
    return {**value, **changes}


def fact(**changes):
    value = {
        "fact_id": "F1", "product_model": MODEL, "claim": "事实原文",
        "evidence_text": "事实原文", "source_ref": "docs/fact.md", "source_type": "official",
        "retrieved_at": "2026-10-22T00:00:00Z", "valid_until": None, "status": "retrieved",
    }
    return {**value, **changes}


def draft(**changes):
    value = {
        "task_summary": "任务摘要", "topic": "主题",
        "audience": {"description": "大学新生", "basis": "用户明确输入", "basis_type": "user_provided"},
        "audience_need": "需求待验证", "core_message": "事实原文", "content_angle": "场景切入",
        "content_format": "小红书图文", "content_outline": [{"section": "开场", "purpose": "提出问题", "fact_references": []}],
        "cta": "", "fact_references": ["F1"], "assumptions": ["需求待验证"],
        "pending_confirmations": [], "risk_notes": [],
    }
    return {**value, **changes}


class WorkflowServiceTests(unittest.TestCase):
    def save_checked_strategy(self, task):
        task, context, _ = self.repo.strategy_snapshot(task["task_id"], task["revision"])
        value = draft()
        claims = [{"field_path": "core_message", "claim": "事实原文", "fact_references": ["F1"]}]
        assessment = {
            "status": "passed", "draft": value, "attempts": 1, "blocking_items": [], "fact_claims": claims,
            "coverage_review": {"fields": [
                {"field_path": path, "text": text, "kind": "factual" if path == "core_message" else "planning",
                 "claims": [text] if path == "core_message" else []} for path, text in _public_texts(value)
            ]},
            "fact_check": FactChecker().check(task, [{"claim": "事实原文", "fact_references": ["F1"]}], context),
        }
        return self.repo.add_strategy(task["task_id"], task["revision"], value, assessment=assessment, context=context)

    def setUp(self):
        self.repo = TaskRepository()
        set_repository(self.repo)
        self.interpret_patch = patch("src.workflow_service.interpret_requirements", return_value={
            "summary": "离线 fixture 需求摘要",
            "updates": {}, "clear_fields": [], "excluded_scenes": [],
            "question": "请提供具体产品或型号？",
        })
        self.interpret_patch.start()
        self.addCleanup(self.interpret_patch.stop)

    def _research_fixture(self, *, status="partial", documents=True, candidates=None, selected=MODEL, on_call=None):
        record = fact(status="retrieved", source_type="other", valid_until=None)
        result = {
            "status": status,
            "query": MODEL,
            "selected_product_model": selected,
            "candidate_models": candidates if candidates is not None else [{"product_model": MODEL, "sources": []}],
            "documents": ([{"document_title": "fixture.md", "source_ref": "P1/fixture.md", "fact_ids": ["F1"]}]
                          if documents else []),
            "fact_records": [record] if documents and status in {"partial", "success"} else [],
            "knowledge_source": {"mode": "local", "name": "任德耀新建华为PC知识库", "live": False,
                                 "status": "ok", "message": "本地只读副本"},
            "warnings": [], "missing_information": [], "next_action": "check_facts",
        }

        class Service:
            mode = "local"

            def retrieve_product_facts(self, query):
                if on_call:
                    on_call(query)
                return result

        return Service(), result

    def _ready_for_research(self, **changes):
        task = self.repo.create(task_payload(**changes))
        task, _ = self.repo.apply_interpretation(task["task_id"], task["revision"], {}, [], [], "离线需求摘要", None)
        return task

    def test_research_route_saves_only_retrieved_facts_and_does_not_claim_strategy_done(self):
        service, _ = self._research_fixture()
        previous = workflow_service.RESEARCH_SERVICE
        set_research_service(service)
        self.addCleanup(set_research_service, previous)
        task = self._ready_for_research()
        status, response = dispatch("/api/agent/research", {
            "task_id": task["task_id"], "expected_revision": task["revision"],
        })
        self.assertEqual(status, 200)
        result = response["data"]["research"]
        self.assertEqual(response["data"]["task"]["workflow_status"], "ready_for_strategy")
        self.assertEqual(response["data"]["task"]["fact_records"][0]["status"], "retrieved")
        self.assertFalse(result["knowledge_source"]["live"])
        self.assertEqual(result["next_action"], "check_facts")
        self.assertNotEqual(result["status"], "strategy_complete")

    def test_ambiguous_product_returns_conflict_without_storing_facts(self):
        service, _ = self._research_fixture(
            status="conflict", documents=False, selected=None,
            candidates=[{"product_model": MODEL, "sources": []},
                        {"product_model": "HUAWEI MateBook X Pro 2021", "sources": []}],
        )
        previous = workflow_service.RESEARCH_SERVICE
        set_research_service(service)
        self.addCleanup(set_research_service, previous)
        task = self._ready_for_research(product_query="MateBook X Pro")
        status, response = dispatch("/api/agent/research", {
            "task_id": task["task_id"], "expected_revision": task["revision"],
        })
        self.assertEqual(status, 409)
        self.assertEqual(response["error"]["code"], "PRODUCT_MODEL_CONFLICT")
        self.assertEqual(response["data"]["research"]["fact_records"], [])
        self.assertEqual(response["data"]["task"]["fact_records"], [])

    def test_product_changed_during_retrieval_discards_stale_results(self):
        task_holder = {}

        def change_product(_query):
            active = self.repo.get(task_holder["task"]["task_id"])
            self.assertEqual(active["workflow_status"], "researching")
            self.repo.update(active["task_id"], active["revision"], {
                "task_id": active["task_id"], "expected_revision": active["revision"],
                "user_input": "改为另一型号", "updates": {"product_query": "Another Exact"},
                "clear_fields": [],
            })

        service, _ = self._research_fixture(on_call=change_product)
        previous = workflow_service.RESEARCH_SERVICE
        set_research_service(service)
        self.addCleanup(set_research_service, previous)
        task_holder["task"] = self._ready_for_research()
        status, response = dispatch("/api/agent/research", {
            "task_id": task_holder["task"]["task_id"], "expected_revision": task_holder["task"]["revision"],
        })
        self.assertEqual(status, 409)
        self.assertEqual(response["error"]["code"], "VERSION_CONFLICT")
        current = self.repo.get(task_holder["task"]["task_id"])
        self.assertEqual(current["product_query"], "Another Exact")
        self.assertEqual(current["fact_records"], [])
        self.assertEqual(current["workflow_status"], "collecting_requirements")

    def test_failed_research_can_be_retried_with_latest_revision(self):
        task = self._ready_for_research()
        task = self.repo.begin_research(task["task_id"], task["revision"])
        failed = self.repo.fail_task(task["task_id"], task["revision"])
        retry = self.repo.begin_research(failed["task_id"], failed["revision"])
        self.assertEqual(retry["workflow_status"], "researching")
        self.assertGreater(retry["revision"], failed["revision"])

    def test_clear_product_can_complete_in_another_thread_while_research_is_blocked(self):
        entered = threading.Event()
        release = threading.Event()
        updated = threading.Event()
        results = {}
        task = self._ready_for_research()

        def block_source(_query):
            entered.set()
            release.wait(timeout=5)

        service, _ = self._research_fixture(on_call=block_source)
        previous = workflow_service.RESEARCH_SERVICE
        set_research_service(service)
        self.addCleanup(set_research_service, previous)

        def research():
            results["research"] = dispatch("/api/agent/research", {
                "task_id": task["task_id"], "expected_revision": task["revision"],
            })

        def clear_product():
            try:
                active = self.repo.get(task["task_id"])
                results["update"] = self.repo.update(task["task_id"], active["revision"], {
                    "task_id": task["task_id"], "expected_revision": active["revision"],
                    "user_input": "清空产品", "updates": {}, "clear_fields": ["product_query"],
                })
            finally:
                updated.set()

        reader = threading.Thread(target=research, daemon=True)
        writer = threading.Thread(target=clear_product, daemon=True)
        reader.start()
        try:
            self.assertTrue(entered.wait(timeout=2), "research did not reach the external source")
            writer.start()
            self.assertTrue(updated.wait(timeout=2), "repository lock was held during the external call")
            self.assertEqual(results["update"]["product_query"], "")
        finally:
            release.set()
            reader.join(timeout=2)
            if writer.ident is not None:
                writer.join(timeout=2)

        self.assertFalse(reader.is_alive())
        self.assertFalse(writer.is_alive())
        status, response = results["research"]
        self.assertEqual(status, 409)
        self.assertEqual(response["error"]["code"], "VERSION_CONFLICT")
        current = self.repo.get(task["task_id"])
        self.assertEqual(current["product_query"], "")
        self.assertEqual(current["field_status"]["product_query"], "cleared")
        self.assertEqual(current["fact_records"], [])

    def test_research_no_result_returns_failure_and_retry_uses_latest_revision(self):
        service, _ = self._research_fixture(status="needs_input", documents=False, selected=None, candidates=[])
        previous = workflow_service.RESEARCH_SERVICE
        set_research_service(service)
        self.addCleanup(set_research_service, previous)
        task = self._ready_for_research()
        status, response = dispatch("/api/agent/research", {
            "task_id": task["task_id"], "expected_revision": task["revision"],
        })
        self.assertEqual(status, 409)
        self.assertFalse(response["success"])
        self.assertEqual(response["error"]["code"], "PRODUCT_NEEDS_INPUT")
        failed = response["data"]["task"]
        self.assertEqual(failed["workflow_status"], "failed")
        self.assertEqual(failed["fact_records"], [])
        self.assertGreater(failed["revision"], task["revision"])
        self.assertIn("recovery", response["data"])

    def test_source_conflict_is_distinct_from_product_ambiguity(self):
        service, result = self._research_fixture(status="conflict", documents=False, selected=None)
        result["error"] = {"code": "SOURCE_CONFLICT", "message": "同型号明确参数不一致。"}
        previous = workflow_service.RESEARCH_SERVICE
        set_research_service(service)
        self.addCleanup(set_research_service, previous)
        task = self._ready_for_research()
        status, response = dispatch("/api/agent/research", {
            "task_id": task["task_id"], "expected_revision": task["revision"],
        })
        self.assertEqual(status, 409)
        self.assertEqual(response["error"]["code"], "SOURCE_CONFLICT")
        self.assertEqual(response["data"]["task"]["fact_records"], [])

    def create_ready_task(self):
        task = self.repo.create(task_payload())
        self.assertEqual(task["workflow_status"], "collecting_requirements")
        task = self.repo.begin_research(task["task_id"], task["revision"])
        self.assertEqual(task["workflow_status"], "researching")
        task = self.repo.complete_research(task["task_id"], task["revision"], [fact()],
            knowledge_source={"mode": "local", "name": "fixture", "live": False, "status": "ok", "message": "fixture"},
            evidence_documents=[{"source_ref": "docs/fact.md", "product_model": MODEL, "content": "事实原文"}],
        )
        self.assertEqual(task["workflow_status"], "ready_for_strategy")
        self.assertEqual(task["fact_records"][0]["status"], "retrieved")
        task, context = self.repo.fact_check_snapshot(task["task_id"], task["revision"])
        claims = [{"claim": "事实原文", "fact_references": ["F1"]}]
        task, checked = self.repo.complete_fact_check(task, context, claims, FactChecker().check(task, claims, context))
        self.assertEqual(checked["eligible_fact_ids"], ["F1"])
        return task

    def test_snapshot_is_deep_copy_and_original_input_does_not_change(self):
        created = self.repo.create(task_payload())
        created["conversation"][0]["text"] = "外部篡改"
        created["field_status"]["scene"] = "cleared"
        snapshot = self.repo.get(created["task_id"])
        self.assertEqual(snapshot["user_input"], "原始需求不变")
        self.assertEqual(snapshot["conversation"][0]["text"], "原始需求不变")
        self.assertEqual(snapshot["field_status"]["scene"], "confirmed")

    def test_clear_field_wins_and_is_not_restored_from_old_conversation(self):
        task = self.repo.create(task_payload())
        updated = self.repo.update(task["task_id"], 1, {
            "task_id": task["task_id"], "expected_revision": 1,
            "user_input": "不再指定场景", "updates": {}, "clear_fields": ["scene"],
        })
        self.assertEqual(updated["scene"], "")
        self.assertEqual(updated["field_status"]["scene"], "cleared")
        self.assertEqual(updated["user_input"], "原始需求不变")
        self.assertEqual(updated["conversation"][-1]["text"], "不再指定场景")

    def test_explicit_update_and_clear_cannot_conflict(self):
        task = self.repo.create(task_payload())
        with self.assertRaises(WorkflowError) as raised:
            self.repo.update(task["task_id"], 1, {
                "task_id": task["task_id"], "expected_revision": 1,
                "user_input": "", "updates": {"scene": "新场景"}, "clear_fields": ["scene"],
            })
        self.assertEqual(raised.exception.code, "INVALID_REQUEST")

    def test_stale_revision_rejected_without_overwriting_newer_snapshot(self):
        task = self.repo.create(task_payload())
        newer = self.repo.update(task["task_id"], 1, {
            "task_id": task["task_id"], "expected_revision": 1,
            "user_input": "改受众", "updates": {"audience": "研究生"}, "clear_fields": [],
        })
        with self.assertRaises(WorkflowError) as raised:
            self.repo.update(task["task_id"], 1, {
                "task_id": task["task_id"], "expected_revision": 1,
                "user_input": "过期写入", "updates": {"audience": "其他"}, "clear_fields": [],
            })
        self.assertEqual(raised.exception.code, "VERSION_CONFLICT")
        self.assertEqual(self.repo.get(task["task_id"])["revision"], newer["revision"])
        self.assertEqual(self.repo.get(task["task_id"])["audience"], "研究生")

    def test_task_context_is_isolated_between_ids(self):
        one = self.repo.create(task_payload())
        two = self.repo.create(task_payload(product_query="Other Exact", audience="企业用户"))
        self.assertNotEqual(one["task_id"], two["task_id"])
        self.assertEqual(self.repo.get(one["task_id"])["product_query"], MODEL)
        self.assertEqual(self.repo.get(two["task_id"])["product_query"], "Other Exact")

    def test_research_refuses_incomplete_required_fields(self):
        task = self.repo.create(task_payload(scene=""))
        with self.assertRaises(WorkflowError) as raised:
            self.repo.begin_research(task["task_id"], task["revision"])
        self.assertEqual(raised.exception.code, "REQUIREMENTS_INCOMPLETE")
        self.assertEqual(self.repo.get(task["task_id"])["workflow_status"], "collecting_requirements")

    def test_product_change_invalidates_retrieved_facts_and_dependent_strategy(self):
        task = self.create_ready_task()
        task, strategy = self.save_checked_strategy(task)
        changed = self.repo.update(task["task_id"], task["revision"], {
            "task_id": task["task_id"], "expected_revision": task["revision"],
            "user_input": "改为另一个精确型号", "updates": {"product_query": "Another Exact"},
            "clear_fields": [],
        })
        self.assertEqual(changed["product_query"], "Another Exact")
        self.assertEqual(changed["fact_records"], [])
        self.assertIsNone(changed["current_strategy_id"])
        self.assertEqual(
            self.repo._strategies[task["task_id"]][strategy["strategy_id"]]["confirmation_status"],
            "superseded",
        )

    def test_research_does_not_mix_multiple_exact_product_models(self):
        task = self.repo.create(task_payload())
        task = self.repo.begin_research(task["task_id"], task["revision"])
        with self.assertRaises(WorkflowError) as raised:
            self.repo.complete_research(task["task_id"], task["revision"], [fact(), fact(fact_id="F2", product_model="Other Exact")])
        self.assertEqual(raised.exception.code, "PRODUCT_MODEL_CONFLICT")
        self.assertEqual(self.repo.get(task["task_id"])["workflow_status"], "researching")

    def test_structured_form_can_create_task_without_free_text(self):
        task = self.repo.create(task_payload(user_input=""))
        self.assertEqual(task["user_input"], "")
        self.assertEqual(task["conversation"], [])

    def test_strategy_metadata_is_server_owned_and_explicitly_confirmed(self):
        task = self.create_ready_task()
        with self.assertRaises(WorkflowError) as raised:
            self.repo.add_strategy(task["task_id"], task["revision"], {**draft(), "strategy_id": "model-choice"})
        self.assertEqual(raised.exception.code, "INVALID_STRATEGY")

        task, strategy = self.save_checked_strategy(task)
        self.assertEqual(strategy["confirmation_status"], "pending")
        self.assertIsNone(strategy["confirmed_at_task_revision"])
        self.assertEqual(task["workflow_status"], "awaiting_user_confirmation")
        with self.assertRaises(WorkflowError):
            self.repo.confirm_strategy(task["task_id"], task["revision"], strategy["strategy_id"], strategy["strategy_version"] + 1)
        confirmed_task, confirmed = self.repo.confirm_strategy(task["task_id"], task["revision"], strategy["strategy_id"], strategy["strategy_version"])
        self.assertEqual(confirmed["confirmation_status"], "confirmed")
        self.assertEqual(confirmed_task["workflow_status"], "strategy_confirmed")

    def test_input_change_supersedes_strategy_and_invalidates_confirmation(self):
        task = self.create_ready_task()
        task, strategy = self.save_checked_strategy(task)
        changed = self.repo.update(task["task_id"], task["revision"], {
            "task_id": task["task_id"], "expected_revision": task["revision"],
            "user_input": "换一个场景", "updates": {"scene": "职场办公"}, "clear_fields": [],
        })
        self.assertEqual(changed["current_strategy_id"], None)
        self.assertEqual(self.repo._strategies[task["task_id"]][strategy["strategy_id"]]["confirmation_status"], "superseded")

    def test_process_repository_serializes_concurrent_updates(self):
        task = self.repo.create(task_payload())
        barrier = __import__("threading").Barrier(2)
        results = []

        def update(audience):
            barrier.wait()
            try:
                result = self.repo.update(task["task_id"], 1, {
                    "task_id": task["task_id"], "expected_revision": 1,
                    "user_input": audience, "updates": {"audience": audience}, "clear_fields": [],
                })
                results.append(result["revision"])
            except WorkflowError as error:
                results.append(error.code)

        threads = [__import__("threading").Thread(target=update, args=(name,)) for name in ("A", "B")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)
        self.assertEqual(sorted(str(item) for item in results), ["2", "VERSION_CONFLICT"])

    def test_understanding_does_not_grant_strategy_eligibility_without_fact_checks(self):
        status, result = dispatch("/api/agent/understand", task_payload())
        self.assertEqual(status, 201)
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["task"]["workflow_status"], "ready_for_strategy")
        self.assertEqual(result["data"]["understanding"]["implementation_status"], "IMPLEMENTED")
        task_id = result["data"]["task"]["task_id"]
        status, strategy = dispatch("/api/strategy/generate", {
            "task_id": task_id, "expected_revision": result["data"]["task"]["revision"],
        })
        self.assertEqual(status, 409)
        self.assertFalse(strategy["success"])
        self.assertEqual(strategy["error"]["code"], "NO_VERIFIED_FACTS")

    def test_final_check_requires_current_confirmed_strategy_version(self):
        task = self.create_ready_task()
        task, strategy = self.save_checked_strategy(task)
        status, result = dispatch("/api/facts/check-final", {
            "task_id": task["task_id"], "expected_revision": task["revision"],
            "strategy_id": strategy["strategy_id"], "strategy_version": strategy["strategy_version"],
            "content": {"title": "t", "body": "b", "cta": "", "plain_text": "b", "images": []},
        })
        self.assertEqual(status, 409)
        self.assertEqual(result["error"]["code"], "STRATEGY_NOT_CONFIRMED")


if __name__ == "__main__":
    unittest.main()
