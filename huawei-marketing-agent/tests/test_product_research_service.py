"""Offline tests for provenance-safe product FactRecord adaptation."""

import unittest

from src.ima_client import ImaClientError

from src.product_research_service import ProductResearchService


MODEL = "HUAWEI MateBook X Pro 酷睿 Ultra 微绒典藏版"
OLD_MODEL = "HUAWEI MateBook X Pro 2021"


def document(content, **changes):
    return {
        "media_id": None,
        "product_model": MODEL,
        "document_title": "产品事实.md",
        "document_type": "md",
        "content": content,
        "source": "P1/产品事实.md",
        "source_ref": "P1/产品事实.md",
        "media": [],
        **changes,
    }


def response(documents=None, **changes):
    value = {
        "status": "success",
        "selected_product_model": MODEL,
        "candidate_models": [{"product_model": MODEL, "sources": []}],
        "documents": documents if documents is not None else [document(
            f"# {MODEL}\n## 已确认事实\n- 处理器为 Ultra 9 185H（仅 Windows）。\n"
            "## 限定条件\n- 该配置仅适用于 Windows 销售 SKU。\n"
            "## 来源\n- https://consumer.huawei.com/example"
        )],
        "knowledge_source": {
            "mode": "local", "name": "任德耀新建华为PC知识库",
            "live": False, "status": "ok", "message": "本地只读副本",
        },
        "warnings": [],
        "missing_information": [],
    }
    return {**value, **changes}


class FixtureKnowledgeService:
    mode = "local"

    def __init__(self, value):
        self.value = value
        self.calls = []

    def retrieve_product_documents(self, query, kb_name):
        self.calls.append((query, kb_name))
        return self.value


class ProductResearchServiceTests(unittest.TestCase):
    def run_research(self, value=None, query=MODEL):
        client = FixtureKnowledgeService(value or response())
        result = ProductResearchService(client).retrieve_product_facts(query)
        return client, result

    def test_exact_model_preserves_configuration_conditions_and_source(self):
        _, result = self.run_research()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["selected_product_model"], MODEL)
        self.assertTrue(result["fact_records"])
        claims = "\n".join(item["claim"] for item in result["fact_records"])
        self.assertIn("Ultra 9 185H（仅 Windows）", claims)
        self.assertIn("仅适用于 Windows 销售 SKU", claims)
        self.assertTrue(all(item["status"] == "retrieved" for item in result["fact_records"]))
        self.assertTrue(all(item["product_model"] == MODEL for item in result["fact_records"]))

    def test_claim_evidence_is_a_verbatim_source_slice(self):
        original = f"# {MODEL}\n## 官方规格摘录\n  - 尺寸：A。  \n\n## 限定条件\n  - 仅适用于 Windows。  \n## 图片使用\n不可生成事实。"
        _, result = self.run_research(response([document(original)]))
        fact = result["fact_records"][0]
        self.assertIn("  - 尺寸：A。", fact["evidence_text"])
        self.assertIn("- 仅适用于 Windows。", fact["evidence_text"])
        self.assertNotIn("不可生成事实", fact["evidence_text"])

    def test_source_type_defaults_to_other_even_if_body_contains_official_url(self):
        _, result = self.run_research()
        self.assertTrue(result["fact_records"])
        self.assertTrue(all(item["source_type"] == "other" for item in result["fact_records"]))

    def test_ambiguous_model_never_combines_candidate_documents(self):
        ambiguous = response(
            status="conflict",
            selected_product_model=None,
            candidate_models=[
                {"product_model": MODEL, "sources": []},
                {"product_model": OLD_MODEL, "sources": []},
            ],
            documents=[],
        )
        _, result = self.run_research(ambiguous, "MateBook X Pro")
        self.assertEqual(result["status"], "conflict")
        self.assertIsNone(result["selected_product_model"])
        self.assertEqual(result["fact_records"], [])

    def test_no_result_requires_more_specific_product(self):
        empty = response(
            status="needs_input", selected_product_model=None, candidate_models=[],
            documents=[], missing_information=["未找到精确资料。"],
        )
        _, result = self.run_research(empty)
        self.assertEqual(result["status"], "needs_input")
        self.assertEqual(result["fact_records"], [])
        self.assertTrue(result["missing_information"])

    def test_conflicting_source_identity_is_not_saved(self):
        conflict = response(
            status="conflict",
            selected_product_model=None,
            candidate_models=[
                {"product_model": MODEL, "sources": []},
                {"product_model": OLD_MODEL, "sources": []},
            ],
            documents=[],
            warnings=["来源指向不同产品型号。"],
        )
        _, result = self.run_research(conflict)
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(result["fact_records"], [])

    def test_unknown_validity_is_explicit_not_inferred_from_retrieval_time(self):
        _, result = self.run_research()
        self.assertTrue(all(item["valid_until"] is None for item in result["fact_records"]))
        self.assertTrue(any("当前有效性仍需确认" in item for item in result["missing_information"]))
        self.assertTrue(all(item["retrieved_at"] != item["valid_until"] for item in result["fact_records"]))

    def test_quota_limited_ima_response_is_error_without_local_fallback_claim(self):
        limited = response(status="error", selected_product_model=None, documents=[], candidate_models=[],
                           knowledge_source={"mode": "ima", "name": "任德耀新建华为PC知识库", "live": False,
                                             "status": "quota_limited", "message": "限额"})
        _, result = self.run_research(limited)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["code"], "KNOWLEDGE_QUOTA_LIMITED")

    def test_expired_source_marks_facts_stale_and_result_partial(self):
        expired = document(
            f"# {MODEL}\n## 已确认事实\n- 屏幕尺寸：14.2 英寸。\n有效期至：2020-01-01"
        )
        _, result = self.run_research(response([expired]))
        self.assertEqual(result["status"], "partial")
        self.assertTrue(result["fact_records"])
        self.assertTrue(all(item["status"] == "stale" for item in result["fact_records"]))
        self.assertTrue(any("已过期资料" in item for item in result["missing_information"]))

    def test_unavailable_source_and_error_response_are_not_needs_input(self):
        unavailable = response(
            status="error",
            knowledge_source={
                "mode": "ima", "name": "任德耀新建华为PC知识库", "live": False,
                "status": "unavailable", "message": "知识来源不可用",
            },
            selected_product_model=None, candidate_models=[], documents=[],
        )
        _, result = self.run_research(unavailable)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["code"], "KNOWLEDGE_SOURCE_UNAVAILABLE")
        self.assertEqual(result["fact_records"], [])

    def test_local_unavailable_with_no_documents_remains_error(self):
        unavailable = response(status="error", selected_product_model=None, documents=[], candidate_models=[],
                               knowledge_source={"mode": "local", "name": "任德耀新建华为PC知识库", "live": False,
                                                 "status": "unavailable", "message": "本地未配置"})
        _, result = self.run_research(unavailable)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["code"], "KNOWLEDGE_SOURCE_UNAVAILABLE")

    def test_local_fallback_source_status_keeps_available_documents_partial(self):
        value = response(status="partial", knowledge_source={
            "mode": "local", "name": "任德耀新建华为PC知识库", "live": False,
            "status": "unavailable", "message": "ima unavailable; local snapshot used",
        })
        _, result = self.run_research(value)
        self.assertEqual(result["status"], "partial")
        self.assertTrue(result["fact_records"])
        self.assertFalse(result["knowledge_source"]["live"])

    def test_missing_product_does_not_call_knowledge_service(self):
        client = FixtureKnowledgeService(response())
        result = ProductResearchService(client).retrieve_product_facts(" ")
        self.assertEqual(result["status"], "needs_input")
        self.assertEqual(client.calls, [])

    def test_same_model_inconsistent_unqualified_parameter_returns_source_conflict(self):
        docs = [document(f"# {MODEL}\n## 尺寸与重量\n- 重量：1 kg。", source_ref="P1/a.md"),
                document(f"# {MODEL}\n## 尺寸与重量\n- 重量：2 kg。", source_ref="P1/b.md")]
        _, result = self.run_research(response(docs))
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(result["error"]["code"], "SOURCE_CONFLICT")
        self.assertEqual(result["fact_records"], [])

    def test_alternative_configurations_are_not_silently_collapsed_into_conflict(self):
        docs = [document(f"# {MODEL}\n## 尺寸与重量\n- 重量：1 kg。\n## 限定条件\n仅适用于 Windows。", source_ref="P1/a.md"),
                document(f"# {MODEL}\n## 尺寸与重量\n- 重量：2 kg。\n## 限定条件\n仅适用于 HarmonyOS。", source_ref="P1/b.md")]
        _, result = self.run_research(response(docs))
        self.assertEqual(result["status"], "success")
        self.assertTrue(any("Windows" in fact["claim"] for fact in result["fact_records"]))
        self.assertTrue(any("HarmonyOS" in fact["claim"] for fact in result["fact_records"]))

    def test_2021_document_is_excluded_even_if_client_returned_it(self):
        docs = response()["documents"] + [document(
            f"# {OLD_MODEL}\n## 屏幕\n- 2021 资料不能混入。", product_model=OLD_MODEL,
            source_ref="P1/2021.md",
        )]
        _, result = self.run_research(response(docs))
        self.assertTrue(result["fact_records"])
        self.assertNotIn("2021", str(result["fact_records"]))
        self.assertTrue(any("已排除" in warning for warning in result["warnings"]))

    def test_dynamic_price_stock_and_expired_activity_are_not_stable_facts(self):
        docs = [document(f"# {MODEL}\n## 已确认事实\n价格：100 元；库存充足；提供上门服务。"),
                document(f"# {MODEL}\n## 已确认事实\n屏幕：14 英寸。\n有效期至：2020-01-01", document_title="优惠活动.md")]
        _, result = self.run_research(response(docs))
        self.assertEqual(result["fact_records"], [])
        self.assertEqual(result["status"], "partial")
        self.assertTrue(any("超过明确有效期" in warning for warning in result["warnings"]))

    def test_unsafe_absolute_source_path_is_not_exposed_as_fact_reference(self):
        _, result = self.run_research(response([document(
            f"# {MODEL}\n## 屏幕\n- 规格原文。", source_ref="C:/private/fixture.md",
        )]))
        self.assertEqual(result["fact_records"], [])
        self.assertNotIn("C:/private", str(result))

    def test_timeout_exception_is_safely_reported_without_credentials(self):
        class FailingSource:
            mode = "ima"

            def retrieve_product_documents(self, *args):
                raise ImaClientError("secret-error-detail", kind="timeout")

        result = ProductResearchService(FailingSource()).retrieve_product_facts(MODEL)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["code"], "KNOWLEDGE_SOURCE_UNAVAILABLE")
        self.assertNotIn("secret-error-detail", str(result))


if __name__ == "__main__":
    unittest.main()
