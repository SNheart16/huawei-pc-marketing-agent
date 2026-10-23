"""Fixed-material lifecycle tests; fixture bytes never represent a real model result."""
from copy import deepcopy
import http.client
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zipfile

import app
from content_b import http as content_http
from content_b.contracts import ContentError, normalize
from content_b.providers import MediaProvider, ROOT
from content_b.service import ContentService


class PregeneratedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.root_patch = patch("content_b.providers.ROOT", root)
        self.root_patch.start()
        folder = root / "ui/assets/pregenerated"
        folder.mkdir(parents=True)
        entries = []
        for platform, prefix in (("公众号", "article"), ("微信朋友圈", "moments"), ("小红书", "red")):
            for index in range(2):
                name = f"{prefix}-{index}.png"
                (folder / name).write_bytes(b"fixture-original-" + name.encode())
                entries.append({"material_id": name[:-4], "url": "/assets/pregenerated/" + name,
                    "product_model": "HUAWEI MateBook X Pro", "platform": platform,
                    "theme": "开学", "contains_text": True, "source_type": "pre_generated",
                    "model_match_scope": "family", "source_note": "离线测试素材", "rights_status": "approved",
                    "visual_check_status": "passed"})
        self.manifest = folder / "manifest.json"
        self.manifest.write_text(json.dumps({"schema_version": "pregenerated/1.0", "assets": entries}), encoding="utf-8")
        self.media = MediaProvider(root / "media", pregenerated_path=self.manifest)
        self.service = ContentService(root / "data", media_provider=self.media)
        self.request = deepcopy(json.loads((ROOT / "content_b/examples.json").read_text(encoding="utf-8"))[0]["request"])
        self.request.update(platform="公众号", image_mode="pregenerated", image_count=3)
        self.request["product_context"] = {"model": "HUAWEI MateBook X Pro 酷睿 Ultra 微绒典藏版", "facts": []}

    def tearDown(self):
        self.service.shutdown()
        self.root_patch.stop()
        self.tmp.cleanup()

    def generate(self, request=None, previous=None):
        job = self.service.start(request or self.request, previous is not None)
        for _ in range(100):
            job = self.service.get_job(job["job_id"])
            if job["status"] in ("completed", "failed"):
                break
            time.sleep(.01)
        self.assertEqual(job["status"], "completed", job)
        return self.service.store.get(job["asset_id"])

    def test_default_and_every_platform_select_original_without_paid_image_or_overlay(self):
        request = deepcopy(self.request)
        del request["image_mode"]
        self.assertEqual(normalize(request)["image_mode"], "pregenerated")
        with patch("content_b.image_client.ImageClient.request") as paid, patch.object(self.media, "render") as renderer:
            for platform in ("公众号", "微信朋友圈", "小红书"):
                request["platform"] = platform
                asset = self.generate(request)
                self.assertEqual(len(asset["images"]), 2)  # Never duplicate to reach requested three.
                self.assertEqual({image["platform"] for image in asset["images"]}, {platform})
                for image in asset["images"]:
                    self.assertEqual(image["visual_check_status"], "unknown")
                    self.assertEqual(image["rights_status"], "unconfirmed")
                    self.assertFalse(image["exact_model_verified"])
                    self.assertEqual(image["render_method"], "pre_generated")
                    self.assertTrue(self.media.export_image(image)[1].startswith(b"fixture-original-"))
                self.assertFalse(asset["can_publish"])
            paid.assert_not_called()
            renderer.assert_not_called()

    def test_order_copy_edit_regenerate_and_clear_selection(self):
        asset = self.generate()
        ids = [image["image_id"] for image in asset["images"]][::-1]
        asset = self.service.mutate(asset["asset_id"], {"expected_version": asset["version"], "selected_image_ids": ids})
        images = deepcopy(asset["images"])
        old_hash = asset["content_hash"]
        asset = self.service.mutate(asset["asset_id"], {"expected_version": asset["version"], "copy": {"body": "保留手动编辑"}})
        self.assertEqual(asset["images"], images)
        self.assertNotEqual(asset["content_hash"], old_hash)
        self.assertEqual(asset["fact_check_status"], "pending")
        asset = self.generate({"asset_id": asset["asset_id"], "expected_version": asset["version"], "scope": "all"}, asset)
        self.assertEqual([image["image_id"] for image in asset["images"]], ids)
        asset = self.service.mutate(asset["asset_id"], {"expected_version": asset["version"], "selected_image_ids": []})
        self.assertEqual(asset["images"], [])
        self.assertTrue(asset["copy"]["body"])
        with self.assertRaises(ContentError):
            self.service.mutate(asset["asset_id"], {"expected_version": asset["version"] - 1, "selected_image_ids": ids})

    def test_mismatched_product_platform_and_missing_file_do_not_fallback(self):
        asset = self.generate()
        for ids in (["moments-0"], ["not-found"]):
            with self.assertRaises(ContentError):
                self.service.mutate(asset["asset_id"], {"expected_version": asset["version"], "selected_image_ids": ids})
        changed = deepcopy(self.request)
        changed["product_context"]["model"] = "HUAWEI MateBook 14"
        empty = self.generate(changed)
        self.assertEqual(empty["images"], [])
        self.assertEqual(empty["status"], "partial")
        self.assertIn("待补充", empty["material_notice"])
        self.media.pregenerated_source_path(asset["images"][0]["url"]).unlink()
        with self.assertRaises(ContentError) as missing:
            self.media.export_image(asset["images"][0])
        self.assertEqual(missing.exception.code, "IMAGE_MISSING")

    def test_unsafe_urls_and_changed_bytes_are_rejected(self):
        for url in ("https://example.com/image.png", "/assets/pregenerated/../../secret.png", "/assets/pregenerated/%2e%2e/%2e%2e/secret.png"):
            with self.assertRaises(ContentError):
                self.media.pregenerated_source_path(url)
        image = self.generate()["images"][0]
        self.media.pregenerated_source_path(image["url"]).write_bytes(b"changed")
        with self.assertRaises(ContentError) as changed:
            self.media.export_image(image)
        self.assertEqual(changed.exception.code, "IMAGE_CHANGED")
        asset = self.service.store.get(next(iter(self.service.store.jobs()))["asset_id"])
        with patch.object(self.service.checker, "check") as checker:
            self.service.check(asset)
            checker.assert_not_called()
        self.assertEqual(asset["fact_check_status"], "pending")
        self.assertEqual(asset["fact_check"]["error_code"], "IMAGE_CHANGED")

    def test_ai_mode_is_rejected_before_copy_or_network(self):
        self.request["image_mode"] = "ai_reference"
        with patch.object(self.service.copy_provider, "generate") as copy, patch("content_b.image_client.ImageClient.request") as paid:
            with self.assertRaises(ContentError) as error:
                self.service.start(self.request)
            self.assertEqual(error.exception.code, "IMAGE_GENERATION_DISABLED")
            copy.assert_not_called()
            paid.assert_not_called()

    def test_http_catalog_and_zip_export_use_selected_originals_in_order(self):
        asset = self.generate()
        asset = self.service.mutate(asset["asset_id"], {"expected_version": asset["version"], "selected_image_ids": ["article-1", "article-0"]})
        with patch.object(content_http, "_service", self.service):
            server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                conn.request("GET", "/api/content/" + asset["asset_id"] + "/export")
                response = conn.getresponse()
                self.assertEqual(response.status, 200)
                with zipfile.ZipFile(io.BytesIO(response.read())) as archive:
                    names = json.loads(archive.read("image-order.json"))
                    self.assertEqual(names, ["01-article-1.png", "02-article-0.png"])
                    self.assertEqual(archive.read(names[0]), self.media.export_image(asset["images"][0])[1])
                conn.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == "__main__":
    unittest.main()
