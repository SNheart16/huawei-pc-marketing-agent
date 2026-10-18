"""Synthetic local snapshots only; never read production knowledge-base files."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.local_kb_client import LocalKbClient


MODEL = "HUAWEI MateBook X Pro 酷睿 Ultra 微绒典藏版"
OLD_MODEL = "HUAWEI MateBook X Pro 2021"


class LocalKbClientTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def text(self, relative, content, encoding="utf-8"):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding=encoding)
        return path

    def image(self, relative):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic-image")
        return path

    def retrieve(self, query=MODEL):
        return LocalKbClient(self.root).retrieve_product_documents(query)

    def test_exact_model_and_utf8_sig_have_only_relative_sources(self):
        self.text(f"products/{MODEL}.md", f"# {MODEL}\n\n开发测试正文", "utf-8-sig")
        result = self.retrieve()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["selected_product_model"], MODEL)
        self.assertEqual(len(result["documents"]), 1)
        self.assertFalse(Path(result["documents"][0]["source_ref"]).is_absolute())
        self.assertNotIn(str(self.root), repr(result))

    def test_2021_and_generic_mentions_do_not_become_selected_facts(self):
        self.text(f"products/{MODEL}.md", f"# {MODEL}\n精确资料")
        self.text(f"old/{OLD_MODEL}.md", f"# {OLD_MODEL}\n旧版本测试正文")
        self.text("cases/MateBook X Pro 长页.md", "# MateBook X Pro 长页\n泛称资料")
        self.text("index.md", f"# 产品索引\n{MODEL}\n{OLD_MODEL}")
        result = self.retrieve()
        self.assertEqual(len(result["documents"]), 1)
        self.assertNotIn("旧版本测试正文", repr(result["documents"]))
        self.assertTrue(any("已排除" in x for x in result["warnings"]))

    def test_ambiguous_query_returns_candidates_without_combining_contents(self):
        self.text(f"products/{MODEL}.md", f"# {MODEL}\n当前版本")
        self.text(f"old/{OLD_MODEL}.md", f"# {OLD_MODEL}\n旧版本")
        result = self.retrieve("MateBook X Pro")
        self.assertEqual(result["status"], "conflict")
        self.assertIsNone(result["selected_product_model"])
        self.assertEqual(len(result["candidate_models"]), 2)
        self.assertEqual(result["documents"], [])

    def test_configuration_variants_are_preserved_and_require_choice(self):
        first = OLD_MODEL + " i5 16GB"
        second = OLD_MODEL + " i7 32GB"
        self.text(f"products/{first}.md", f"# {first}\n配置一")
        self.text(f"products/{second}.md", f"# {second}\n配置二")
        result = self.retrieve(OLD_MODEL)
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(result["documents"], [])
        self.assertEqual({item["product_model"] for item in result["candidate_models"]}, {first, second})
        precise = self.retrieve(first)
        self.assertEqual(len(precise["documents"]), 1)
        self.assertEqual(precise["selected_product_model"], first)

    def test_generic_document_cannot_hide_more_specific_configuration_candidates(self):
        self.text(f"products/{OLD_MODEL}.md", f"# {OLD_MODEL}\n通用版本资料")
        for configuration in ("i5 16GB", "i7 32GB"):
            self.text(f"products/{OLD_MODEL} {configuration}.md", f"# {OLD_MODEL} {configuration}\n配置资料")
        result = self.retrieve(OLD_MODEL)
        self.assertEqual(result["status"], "conflict")
        self.assertIsNone(result["selected_product_model"])
        self.assertEqual(result["documents"], [])

    def test_later_h1_or_h2_other_model_makes_entire_document_unsafe_for_facts(self):
        for level in ("#", "##"):
            with self.subTest(level=level):
                self.text(f"products/{MODEL}.md", f"# {MODEL}\n本款资料\n{level} {OLD_MODEL}\n旧版参数")
                result = self.retrieve()
                self.assertIsNone(result["selected_product_model"])
                self.assertEqual(result["documents"], [])
                self.assertTrue(any("多个型号身份" in warning for warning in result["warnings"]))

    def test_other_model_year_in_plain_prose_cannot_leak_old_parameters(self):
        self.text(f"products/{MODEL}.md", f"# {MODEL}\n当前版资料\n{OLD_MODEL}: old edition CPU and memory specifications.")
        result = self.retrieve()
        self.assertIsNone(result["selected_product_model"])
        self.assertEqual(result["documents"], [])

    def test_plain_capture_dates_and_descriptive_edition_prose_are_not_model_identities(self):
        self.text(f"products/{MODEL}.md", f"# {MODEL}\n抓取日期：2021-01-01。\nMateBook X Pro 的资料更新于 2021 年。\nMateBook X Pro 2021-01-01 抓取记录。\nMateBook X Pro notes on Edition information.\nMateBook X Pro 最新版本仍需复核。\nMateBook X Pro 是一款需要复核版本的产品。")
        result = self.retrieve()
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["documents"]), 1)

    def test_other_explicit_edition_in_plain_prose_is_excluded(self):
        for other in ("HUAWEI MateBook X Pro Signature Edition", "HUAWEI MateBook X Pro 青春版"):
            with self.subTest(other=other):
                self.text(f"products/{MODEL}.md", f"# {MODEL}\n另款信息：{other}，独立产品资料。")
                self.assertEqual(self.retrieve()["documents"], [])

    def test_another_model_dedicated_parent_directory_is_conflicting_identity(self):
        self.text(f"{OLD_MODEL}/{MODEL}.md", f"# {MODEL}\n当前版标题被放入旧款目录")
        result = self.retrieve()
        self.assertIsNone(result["selected_product_model"])
        self.assertEqual(result["documents"], [])

    def test_optional_brand_and_document_suffix_do_not_create_conflicts(self):
        unbranded = MODEL.removeprefix("HUAWEI ")
        self.text("products/产品事实.md", f"# {unbranded} - 产品事实\n具体事实")
        result = self.retrieve()
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["documents"]), 1)

    def test_cross_product_comparisons_are_excluded(self):
        self.text(f"products/{MODEL}.md", f"# {MODEL}\n本型号正文")
        self.text("竞品资料/比较.md", f"# Other Model 与 {MODEL}\n跨产品比较")
        result = self.retrieve()
        self.assertEqual(len(result["documents"]), 1)
        self.assertNotIn("跨产品比较", repr(result["documents"]))

    @unittest.skipUnless(os.name == "nt", "Windows file attributes")
    def test_windows_hidden_file_attribute_is_ignored(self):
        import ctypes
        hidden = self.text(f"products/{MODEL}.md", f"# {MODEL}\n隐藏资料")
        self.assertTrue(ctypes.windll.kernel32.SetFileAttributesW(str(hidden), 0x2))
        try:
            result = self.retrieve()
            self.assertEqual(result["documents"], [])
        finally:
            ctypes.windll.kernel32.SetFileAttributesW(str(hidden), 0x80)

    def test_nearby_image_is_unknown_and_explicit_reference_is_confirmed(self):
        self.text(f"products/{MODEL}.md", f"# {MODEL}\n![明确引用](../images/confirmed.png)")
        self.image("images/confirmed.png")
        self.image("MateBook X系列/images/matebook-x-pro-ultra.jpg")
        result = self.retrieve()
        self.assertEqual(result["image_counts"], {"confirmed": 1, "unknown": 1})
        unknown = [x for x in result["media"] if x["status"] == "unknown"][0]
        self.assertIsNone(unknown["url"])
        self.assertIsNone(unknown["product_model"])
        self.assertEqual(len(result["documents"][0]["media"]), 1)

    def test_dedicated_directory_and_complete_filename_confirm_images(self):
        self.text(f"{MODEL}/card.md", f"# 产品卡\n产品型号：{MODEL}")
        self.image(f"{MODEL}/images/appearance.png")
        self.image(f"shared/{MODEL}-外观.webp")
        result = self.retrieve()
        self.assertEqual(result["image_counts"], {"confirmed": 2, "unknown": 0})

    def test_generic_adjacent_image_is_unknown_without_explicit_model_evidence(self):
        self.text(f"products/{MODEL}.md", f"# {MODEL}\n没有引用图片")
        self.image("products/images/appearance.jpg")
        result = self.retrieve()
        self.assertEqual(result["image_counts"], {"confirmed": 0, "unknown": 1})
        self.assertEqual(result["media"][0]["status"], "unknown")

    def test_cross_model_image_is_unknown_even_when_exact_document_references_it(self):
        query = "HUAWEI MateBook X Pro Signature Edition"
        filename = query + "-vs-HUAWEI MateBook X Pro2021.jpg"
        self.image("products/" + filename)
        self.text(f"products/{query}.md", f"# {query}\n![比较图片](<{filename}>)")
        result = self.retrieve(query)
        self.assertEqual(result["image_counts"], {"confirmed": 0, "unknown": 1})
        self.assertIsNone(result["media"][0]["product_model"])
        self.assertIsNone(result["media"][0]["match_basis"])

    def test_explicit_reference_cannot_override_a_different_model_image_name(self):
        self.image(f"products/{OLD_MODEL}.jpg")
        self.text(f"products/{MODEL}.md", f"# {MODEL}\n![旧款](<{OLD_MODEL}.jpg>)")
        result = self.retrieve()
        self.assertEqual(result["image_counts"], {"confirmed": 0, "unknown": 1})

    def test_missing_environment_variable_returns_safe_unavailable_result(self):
        with patch.dict(os.environ, {}, clear=True):
            result = LocalKbClient().retrieve_product_documents(MODEL)
        self.assertEqual(result["knowledge_source"]["status"], "unavailable")
        self.assertEqual(result["documents"], [])
        self.assertTrue(any("LOCAL_KB_PATH" in x for x in result["missing_information"]))

    def test_hidden_metadata_temporary_and_bad_encoding_are_skipped(self):
        self.text(f"products/{MODEL}.md", f"# {MODEL}\n有效正文")
        for directory in ("__MACOSX", "__MACOSX__", ".history", ".hidden"):
            self.text(f"{directory}/{MODEL}.md", f"# {MODEL}\n不应读取")
        self.text(f"products/._{MODEL}.md", f"# {MODEL}\n不应读取")
        bad = self.text("bad.txt", "placeholder")
        bad.write_bytes(b"\xff\xfe")
        result = self.retrieve()
        self.assertEqual(len(result["documents"]), 1)
        self.assertTrue(any("UTF-8" in x for x in result["warnings"]))

    def test_external_image_reference_cannot_escape_snapshot(self):
        self.text(f"products/{MODEL}.md", f"# {MODEL}\n![outside](../../outside.png)")
        self.image("unrelated.png")
        result = self.retrieve()
        self.assertEqual(result["image_counts"], {"confirmed": 0, "unknown": 0})


if __name__ == "__main__":
    unittest.main()
