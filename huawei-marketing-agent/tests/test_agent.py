"""Offline Agent contracts using temporary prompts, documents, and images.

All knowledge retrieval and model calls are patched; these tests never inspect
the real knowledge-base copy, use real credentials, or make network requests.
"""

import base64
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.agent import run_agent


MODEL = "HUAWEI MateBook X Pro 酷睿 Ultra 微绒典藏版"
OLD_MODEL = "HUAWEI MateBook X Pro 2021"
FACT = "该型号采用合成测试屏幕。"
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aWQAAAABJRU5ErkJggg=="
)


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        prompt = self.root / "system.md"
        prompt.write_text(
            "你是华为 PC 营销图文智能体。只能使用知识库中当前精确型号的明确原文。"
            "先输出场景和证据规划，再依据证据生成严格 JSON。每条产品事实引用 evidence_id。"
            "禁止混入其他年份或配置，禁止虚构产品参数、价格、优惠、个人体验、绝对化宣传。"
            "图片只使用已有资源编号，不得补造来源或链接。未知图片不计入确认数量。"
            "事实冲突必须停止生成；缺失信息应明确说明。保持所有字段符合 JSON v1.0。",
            encoding="utf-8",
        )
        self.environment = {
            "USE_MOCK": "false", "KNOWLEDGE_SOURCE_MODE": "local",
            "LOCAL_KB_PATH": str(self.root), "SYSTEM_PROMPT_PATH": str(prompt),
            "LLM_API_KEY": "synthetic-unit-test-secret", "LLM_BASE_URL": "https://example.invalid/v1",
            "LLM_MODEL": "synthetic-unit-test-model",
        }
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, self.environment, clear=True).start()
        self.knowledge_class = patch("src.agent.KnowledgeService", create=True).start()
        self.llm_class = patch("src.agent.LLMClient", create=True).start()
        # Exercise link-dependent status handling without any HTTP requests.
        self.image_probe = patch("src.agent._probe_image", return_value=True, create=True).start()
        self.knowledge = self.knowledge_class.return_value
        self.llm = self.llm_class.return_value
        self.input = {
            "product_query": MODEL, "audience": "大学新生", "scene": "开学季",
            "platform": "小红书", "goal": "围绕真实事实介绍产品",
            "extra_requirements": "表达克制，不虚构个人体验、价格或优惠。",
        }
        self.source = self.source_result()
        self.plan = {
            "scenario": {
                "purchase_stage": "了解产品", "user_problems": ["如何核对产品事实"],
                "strategy": "用知识库原句说明产品，邀请用户核对所选版本。",
            },
            "evidence": [{
                "evidence_id": "E1", "product_model": MODEL, "fact": FACT,
                "source_title": "synthetic-card.md", "source_ref": "products/synthetic-card.md",
                "media_ids": [],
            }],
            "forbidden_information": ["未知价格", "个人体验", "其他型号参数"],
            "image_suggestions": [],
        }
        self.generated = {
            "content": {
                "title": "开学桌面，先核对这些产品信息", "subtitle": None, "lead": None,
                "body": "开学准备一张学习桌面。\n\n" + FACT + "[E1]",
                "selling_points": [FACT + "[E1]"], "cta": "了解产品时，请核对具体版本。",
                "tags": ["开学季", "学习桌面"], "activity_note": None,
                "images": [], "plain_text": "模型伪造的另一份复制文本，应由程序覆盖。",
            },
            "checks": {
                "facts": [{"claim": FACT, "status": "pass", "evidence_ids": ["E1"], "note": "引用原句。"}],
                "images": [], "compliance": [], "risks": [], "missing_information": [],
            },
        }
        self.knowledge.retrieve_product_documents.side_effect = lambda *args, **kwargs: copy.deepcopy(self.source)
        self.llm.generate_json.side_effect = self.model_response

    def source_result(self, count=3, confirmed=True, linked=True):
        media = []
        folder = self.root / "products"
        folder.mkdir(exist_ok=True)
        (folder / "synthetic-card.md").write_text("# " + MODEL + "\n\n" + FACT, encoding="utf-8")
        for number in range(1, count + 1):
            filename = f"image{number}.png"
            (folder / filename).write_bytes(PNG)
            media.append({
                "media_id": f"img{number}", "image_id": f"M{number}", "name": filename,
                "url": f"https://example.invalid/{filename}" if linked else None,
                "source": f"products/{filename}", "source_ref": f"products/{filename}",
                "product_model": MODEL if confirmed else None,
                "status": "confirmed" if confirmed else "unknown",
            })
        return {
            "status": "success", "query": MODEL, "selected_product_model": MODEL,
            "candidate_models": [{"product_model": MODEL, "sources": []}],
            "documents": [{
                "media_id": None, "product_model": MODEL, "document_title": "synthetic-card.md",
                "content": "# " + MODEL + "\n\n" + FACT,
                "source": "products/synthetic-card.md", "source_ref": "products/synthetic-card.md",
                "media": copy.deepcopy(media),
            }],
            "media": media, "warnings": [], "missing_information": [],
            "knowledge_source": {
                "mode": "local", "name": "合成测试知识库", "live": False,
                "status": "ok", "message": "使用合成测试本地只读副本。",
            },
        }

    def model_response(self, system_prompt, payload):
        self.assertIsInstance(system_prompt, str)
        self.assertIsInstance(payload, dict)
        if payload.get("stage") == "plan":
            return copy.deepcopy(self.plan)
        self.assertEqual(payload.get("stage"), "generate")
        result = copy.deepcopy(self.generated)
        resources = payload.get("images", [])
        result["content"]["images"] = [{
            "image_id": item.get("image_id", f"M{index}"),
            "name": item.get("name"), "url": item.get("url"),
            "source_title": item.get("source_title") or "合成图片",
            "source_ref": item.get("source_ref"), "product_model": MODEL,
            "caption": "合成测试配图，需以资料为准。", "suggested_position": "正文后",
            "status": "pass", "evidence_ids": ["E1"],
        } for index, item in enumerate(resources, 1)]
        return result

    def assert_blocked(self, result):
        self.assertIn(result["status"], {"error", "conflict", "needs_input"})
        self.assertIsNone(result["content"])

    def test_missing_required_input_never_calls_model(self):
        del self.input["audience"]
        result = run_agent(self.input)
        self.assertEqual(result["status"], "needs_input")
        self.assertIsNone(result["content"])
        self.assertTrue(result["checks"]["questions"])
        self.llm.generate_json.assert_not_called()

    def test_ambiguous_product_never_calls_model(self):
        self.input["product_query"] = "MateBook X Pro"
        self.source.update(status="needs_input", selected_product_model=None, documents=[])
        result = run_agent(self.input)
        self.assertEqual(result["status"], "needs_input")
        self.assertIsNone(result["content"])
        self.llm.generate_json.assert_not_called()

    def test_knowledge_conflict_stops_before_both_model_stages(self):
        self.source.update(status="conflict", selected_product_model=None, documents=[])
        self.source["candidate_models"].append({"product_model": OLD_MODEL, "sources": [{"source_ref": "old/card.md"}]})
        result = run_agent(self.input)
        self.assertEqual(result["status"], "conflict")
        self.assertIsNone(result["content"])
        self.llm.generate_json.assert_not_called()

    def test_generation_model_conflict_or_needs_input_prevents_final_copy(self):
        for status in ("conflict", "needs_input"):
            with self.subTest(status=status):
                self.generated["status"] = status
                result = run_agent(self.input)
                self.assertEqual(result["status"], status)
                self.assertIsNone(result["content"])

    def test_generation_model_compliance_failure_is_preserved_and_blocks_copy(self):
        failed_check = {
            "type": "synthetic_policy_review", "status": "fail",
            "note": "合成核验发现待处理的合规问题。",
        }
        self.generated["checks"]["compliance"] = [failed_check]
        # Passing product facts do not override an explicit compliance failure.
        self.assertEqual(self.generated["checks"]["facts"][0]["status"], "pass")
        result = run_agent(self.input)
        self.assertEqual(result["status"], "error")
        self.assertIsNone(result["content"])
        self.assertIn(failed_check, result["checks"]["compliance"])

    def test_summary_audit_outside_copy_does_not_override_real_fact_validation(self):
        self.generated["checks"]["facts"].append({
            "claim": "未编造产品参数，文案仅使用所给资料。", "status": "pass",
            "evidence_ids": [], "note": "概括性自查，不是文案中的产品事实。",
        })
        result = run_agent(self.input)
        self.assertIn(result["status"], {"success", "partial"})
        self.assertIn(FACT, result["content"]["plain_text"])
        self.assertTrue(any(
            row.get("type") == "model_audit_scope" and row.get("status") == "warning"
            for row in result["checks"]["compliance"]
        ))
        self.assertTrue(any(
            row.get("claim") == FACT and row.get("status") == "pass"
            for row in result["checks"]["facts"]
        ))

    def test_uncited_platform_compatibility_and_waterproof_claims_are_blocked(self):
        original = self.generated["content"]["body"]
        for unsupported in (
            "可运行安卓应用。",
            "Windows版与Linux版功能完全一致。",
            "机身防水，雨中照常办公。",
        ):
            with self.subTest(claim=unsupported):
                self.generated["content"]["body"] = original + "\n\n" + unsupported
                self.assert_blocked(run_agent(self.input))

    def test_missing_llm_configuration_does_not_return_mock_copy(self):
        del os.environ["LLM_API_KEY"]
        result = run_agent(self.input)
        self.assertEqual(result["status"], "error")
        self.assertIsNone(result["content"])
        self.llm.generate_json.assert_not_called()

    def test_mock_mode_is_rejected(self):
        os.environ["USE_MOCK"] = "true"
        result = run_agent(self.input)
        self.assertEqual(result["status"], "error")
        self.assertIsNone(result["content"])
        self.llm.generate_json.assert_not_called()

    def test_unavailable_prompt_stops_generation(self):
        os.environ["SYSTEM_PROMPT_PATH"] = str(self.root / "not-created.md")
        result = run_agent(self.input)
        self.assertEqual(result["status"], "error")
        self.assertIsNone(result["content"])
        self.llm.generate_json.assert_not_called()

    def test_success_has_two_stages_v1_contract_and_program_generated_plain_text(self):
        result = run_agent(self.input)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["schema_version"], "1.0")
        self.assertEqual(result["scenario"]["product_model"], MODEL)
        self.assertEqual(result["knowledge_source"]["mode"], "local")
        self.assertFalse(result["knowledge_source"]["live"])
        self.assertEqual(self.llm.generate_json.call_count, 2)
        self.assertEqual([call.args[1]["stage"] for call in self.llm.generate_json.call_args_list], ["plan", "generate"])
        self.assertIn(result["content"]["title"], result["content"]["plain_text"])
        self.assertIn(FACT, result["content"]["plain_text"])
        self.assertNotIn("模型伪造", result["content"]["plain_text"])
        self.assertEqual(result["evidence"][0]["source_ref"], "products/synthetic-card.md")
        json.dumps(result, ensure_ascii=False)

    def test_insufficient_images_keep_copy_and_return_partial(self):
        self.source = self.source_result(count=0)
        result = run_agent(self.input)
        self.assertEqual(result["status"], "partial")
        self.assertIsInstance(result["content"], dict)
        self.assertTrue(result["content"]["plain_text"])
        self.assertTrue(result["checks"]["missing_information"])

    def test_unknown_images_cannot_be_promoted_by_model(self):
        self.source = self.source_result(confirmed=False)
        result = run_agent(self.input)
        self.assertEqual(result["status"], "partial")
        self.assertFalse(any(image["status"] == "pass" for image in result["content"]["images"]))

    def test_local_images_without_links_remain_partial_even_when_files_exist(self):
        self.source = self.source_result(linked=False)
        result = run_agent(self.input)
        self.assertEqual(result["status"], "partial")
        self.assertIsInstance(result["content"], dict)
        self.assertFalse(any(image["status"] == "pass" for image in result["content"]["images"]))

    def test_model_cannot_invent_evidence_before_generation(self):
        self.plan["evidence"][0]["fact"] = "这台产品拥有未在资料出现的十倍性能。"
        result = run_agent(self.input)
        self.assert_blocked(result)
        self.assertEqual(self.llm.generate_json.call_count, 1)

    def test_fabricated_price_is_blocked_even_with_existing_evidence_id(self):
        self.generated["content"]["body"] += "\n仅售3999元[E1]"
        self.generated["checks"]["facts"].append({
            "claim": "仅售3999元", "status": "pass", "evidence_ids": ["E1"], "note": "模型宣称通过",
        })
        self.assert_blocked(run_agent(self.input))

    def test_absolute_advertising_is_blocked(self):
        self.generated["content"]["body"] += "\n全网第一，绝对最好用！[E1]"
        self.assert_blocked(run_agent(self.input))

    def test_factual_sentence_without_inline_evidence_is_blocked(self):
        self.generated["content"]["body"] = FACT
        self.assert_blocked(run_agent(self.input))

    def test_nonexistent_evidence_id_is_blocked(self):
        self.generated["content"]["body"] = FACT + "[E999]"
        self.generated["checks"]["facts"][0]["evidence_ids"] = ["E999"]
        self.assert_blocked(run_agent(self.input))

    def test_other_model_in_generated_copy_is_blocked(self):
        self.generated["content"]["title"] = OLD_MODEL + "开学体验"
        self.assert_blocked(run_agent(self.input))

    def test_cited_source_reference_date_is_not_treated_as_model_year(self):
        dated_fact = "资料基准日期为2026-10-17。"
        self.source["documents"][0]["content"] = "# " + MODEL + "\n\n" + dated_fact
        self.plan["evidence"][0]["fact"] = dated_fact
        self.generated["content"]["body"] = dated_fact + "[E1]"
        self.generated["content"]["selling_points"] = []
        self.generated["checks"]["facts"][0]["claim"] = dated_fact
        result = run_agent(self.input)
        self.assertIn(result["status"], {"success", "partial"})
        self.assertEqual(result["scenario"]["product_model"], MODEL)
        self.assertEqual(result["evidence"][0]["fact"], dated_fact)
        self.assertIn(dated_fact, result["content"]["plain_text"])

    def test_lost_numeric_qualifier_is_blocked(self):
        original = "机身重量约980克（具体以实物为准）。"
        self.source["documents"][0]["content"] = "# " + MODEL + "\n" + original
        self.plan["evidence"][0]["fact"] = original
        self.generated["content"]["body"] = "机身重量980克。[E1]"
        self.generated["content"]["selling_points"] = []
        self.generated["checks"]["facts"][0]["claim"] = "机身重量980克。"
        self.assert_blocked(run_agent(self.input))

    def test_processor_section_cannot_lose_following_windows_condition(self):
        processor = "该型号采用合成测试处理器。"
        condition = "上述处理器功能仅适用于 Windows 系统，具体以对应配置为准。"
        self.source["documents"][0]["content"] = (
            "# " + MODEL + "\n\n## 处理器\n" + processor + "\n\n" + condition
        )
        # The CPU sentence exists verbatim, but omits the same section's
        # condition across a paragraph boundary and must not become evidence.
        self.plan["evidence"][0]["fact"] = processor
        result = run_agent(self.input)
        self.assert_blocked(result)
        self.assertEqual(self.llm.generate_json.call_count, 1)
        self.assertEqual(self.llm.generate_json.call_args.args[1]["stage"], "plan")

    def test_image_position_cannot_hide_absolute_claim_or_fabricated_price(self):
        for position in ("行业第一主视觉，放在标题下方", "售价999元，放在正文后"):
            with self.subTest(position=position):
                def response(system_prompt, payload):
                    result = self.model_response(system_prompt, payload)
                    if payload.get("stage") == "generate":
                        result["content"]["images"][0]["suggested_position"] = position
                    return result

                self.llm.generate_json.side_effect = response
                self.assert_blocked(run_agent(self.input))

    def test_image_position_cannot_hide_unsupported_memory_configuration(self):
        def response(system_prompt, payload):
            result = self.model_response(system_prompt, payload)
            if payload.get("stage") == "generate":
                result["content"]["images"][0]["suggested_position"] = "搭载64GB内存，放在正文后"
            return result

        self.llm.generate_json.side_effect = response
        self.assert_blocked(run_agent(self.input))

    def test_uncited_function_claim_is_blocked_but_user_need_is_allowed(self):
        original = self.generated["content"]["body"]
        cases = (
            ("这台电脑支持量子通信。", False),
            ("选购时可以先想想多设备协同需求。", True),
        )
        for addition, allowed in cases:
            with self.subTest(addition=addition):
                # Keep the valid, cited product fact present in both cases.
                self.generated["content"]["body"] = original + "\n\n" + addition
                result = run_agent(self.input)
                if allowed:
                    self.assertIn(result["status"], {"success", "partial"})
                    self.assertIsInstance(result["content"], dict)
                    self.assertIn(addition, result["content"]["plain_text"])
                else:
                    self.assert_blocked(result)

    def test_sensitive_source_path_never_reaches_final_output(self):
        unsafe = "D:\\private-synthetic-location\\card.md"
        self.source["documents"][0].update(source_ref=unsafe, source=unsafe)
        self.plan["evidence"][0]["source_ref"] = unsafe
        result = run_agent(self.input)
        self.assertNotIn(unsafe, json.dumps(result, ensure_ascii=False))
        self.assertNotIn("private-synthetic-location", json.dumps(result, ensure_ascii=False))

    def test_client_exception_details_are_not_leaked(self):
        secret = "synthetic-never-log-secret"
        self.knowledge.retrieve_product_documents.side_effect = RuntimeError(
            f"Authorization: Bearer {secret}; Cookie: hidden; directory={self.root}"
        )
        result = run_agent(self.input)
        self.assertEqual(result["status"], "error")
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertNotIn(secret, serialized)
        self.assertNotIn(str(self.root), serialized)


if __name__ == "__main__":
    unittest.main()
