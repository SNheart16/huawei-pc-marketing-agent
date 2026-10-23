"""Image integration contracts; these tests never call a paid service."""
from copy import deepcopy
import base64
import io
import json
import os
from pathlib import Path
import struct
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.error import URLError
import zlib

import app
from content_b.config import load_config
from content_b.contracts import ContentError, normalize
from content_b.image_client import ImageClient, build_prompt, png_dimensions
from content_b.providers import MediaProvider, ROOT, CopyProvider
from content_b.service import ContentService
from content_b.references import register_reference, image_info


def png():
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(b'\x00\xff\xff\xff')) + chunk(b'IEND', b''))


class ImageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.r = normalize(deepcopy(json.loads((ROOT / 'content_b/examples.json').read_text(encoding='utf-8'))[0]['request']))
        self.r['image_mode'] = 'ai_reference'
        self.c = {'title': '一张学习清单', 'body': '先整理任务', 'cta': '', 'hashtags': []}
        self.env = patch.dict(os.environ, {'IMAGE_API_KEY': 'test-secret', 'IMAGE_BASE_URL': 'https://provider.example/v1', 'IMAGE_MODEL': 'test-image', 'IMAGE_TIMEOUT': '180'})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_png_validation_rejects_corrupt_truncated_and_non_png(self):
        self.assertEqual(png_dimensions(png()), (1, 1))
        for value in (b'<svg/>', png()[:-1], png()[:40] + b'x' + png()[41:]):
            with self.assertRaises(ContentError):
                png_dimensions(value)

    def test_multipart_decodes_bytes_and_does_not_expose_credential(self):
        client = ImageClient()
        response = io.BytesIO(json.dumps({'data': [{'b64_json': base64.b64encode(png()).decode()}]}).encode())
        with patch.object(client.opener, 'open', return_value=response) as call:
            self.assertEqual(client.request(b'original', 'prompt', '1024x1536'), png())
            req = call.call_args.args[0]
            self.assertIn(b'name="image"', req.data)
            self.assertIn(b'original', req.data)
            self.assertNotIn(b'test-secret', req.data)
            self.assertEqual(req.full_url, 'https://provider.example/v1/images/edits')

    def test_http_failure_hides_body_and_never_retries(self):
        client = ImageClient()
        error = HTTPError(client.endpoint, 429, 'secret-message', {}, io.BytesIO(b'test-secret'))
        with patch.object(client.opener, 'open', side_effect=error) as call:
            with self.assertRaises(ContentError) as caught:
                client.request(b'original', 'prompt', '1024x1536')
        self.assertEqual(call.call_count, 1)
        self.assertNotIn('secret', str(caught.exception))
        self.assertIn('429', str(caught.exception))

    def test_temporary_url_is_not_saved_as_generated_image(self):
        client = ImageClient()
        with patch.object(client.opener, 'open', return_value=io.BytesIO(b'{"data":[{"url":"https://example.com/image"}]}')):
            with self.assertRaises(ContentError) as error:
                client.request(b'original', 'prompt', '1024x1536')
        self.assertEqual(error.exception.code, 'IMAGE_RESPONSE')

    def test_generated_metadata_is_honest_and_keeps_reference_fingerprint(self):
        media = MediaProvider(Path(self.temp.name) / 'media')
        with patch.object(ImageClient, 'request', return_value=png()):
            result = media.render(self.r, self.c)
        self.assertTrue((media.media_dir / (result['image_id'] + '.png')).is_file())
        self.assertTrue(result['is_generated'])
        self.assertEqual(result['text_content_status'], 'intended_not_ocr_verified')
        self.assertEqual(result['visual_check_status'], 'needs_review')
        self.assertEqual(result['rights_status'], 'unconfirmed')
        self.assertEqual(len(result['source_sha256']), 64)
        self.assertNotIn('test-secret', json.dumps(result))
        self.assertIn(self.c['title'], result['generation_prompt'])

    def test_missing_reference_makes_no_network_call(self):
        self.r['product_context']['model'] = 'unregistered model'
        with patch.object(ImageClient, 'request') as call:
            with self.assertRaises(ContentError):
                MediaProvider(Path(self.temp.name)).render(self.r, self.c)
        call.assert_not_called()

    def test_catalog_replacement_never_calls_paid_image_service(self):
        with patch.object(ImageClient, 'request') as call:
            result = MediaProvider(Path(self.temp.name)).render(self.r, self.c, 0, 'pro-s-angle')
        call.assert_not_called()
        self.assertFalse(result['is_generated'])

    def test_prompt_carries_audience_and_adjustment_but_no_unverified_specs(self):
        self.r['image_adjustment'] = '不要岩石，改成暖光'
        prompt, texts, role = build_prompt(self.r, self.c, 1)
        self.assertIn(self.r['strategy']['audience'], prompt)
        self.assertIn(self.r['image_adjustment'], prompt)
        self.assertEqual(role, '场景清单')
        self.assertIn('AI 创意参考图 · 产品外观以实物为准', texts)

    def test_configuration_rejects_redirectable_or_unsafe_endpoint(self):
        for url in ('http://provider.example', 'https://a:b@provider.example', 'https://provider.example?secret=x'):
            with patch.dict(os.environ, {'IMAGE_BASE_URL': url}), self.assertRaises(ContentError):
                ImageClient()

    def test_explicit_config_preserves_environment_and_never_evaluates_shell(self):
        path = Path(self.temp.name) / '.env'
        path.write_text("LLM_MODEL='file-model'\nLLM_API_KEY=$(no-shell)\n", encoding='utf-8')
        with patch.dict(os.environ, {'LLM_MODEL': 'process-model'}, clear=True):
            load_config(path)
            self.assertEqual(os.environ['LLM_MODEL'], 'process-model')
            self.assertEqual(os.environ['LLM_API_KEY'], '$(no-shell)')
        path.write_text('PATH=unsafe\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            load_config(path)

    def test_copy_schema_quality_repair_is_bounded(self):
        self.r['copy_mode'] = 'llm'
        with patch('src.llm_client.LLMClient') as client:
            client.return_value.generate_json.side_effect = [{**self.c, 'title': '过长' * 30}, self.c]
            self.assertEqual(CopyProvider().generate(self.r), self.c)
            self.assertEqual(client.return_value.generate_json.call_count, 2)

    def test_ai_mode_is_disabled_before_copy_or_paid_calls(self):
        svc = ContentService(self.temp.name)
        try:
            with patch.object(ImageClient, 'request', side_effect=ContentError('IMAGE_TIMEOUT', '等待超时', 502)) as call:
                with self.assertRaises(ContentError) as error:
                    svc.start(self.r)
                self.assertEqual(error.exception.code, 'IMAGE_GENERATION_DISABLED')
                call.assert_not_called()
        finally:
            svc.shutdown()

    def test_upload_registers_png_and_keeps_exact_model_boundary(self):
        media = MediaProvider(Path(self.temp.name) / 'media')
        item = register_reference(media, {'model': 'HUAWEI MateBook X Pro', 'image_base64': base64.b64encode(png()).decode()})
        self.assertEqual(media.list('HUAWEI MateBook X Pro')[0]['catalog_id'], item['catalog_id'])
        self.assertEqual(item['rights_status'], 'unconfirmed')
        self.r['product_context']['model'] = 'HUAWEI MateBook X Pro'
        self.r['reference_id'] = item['catalog_id']
        with patch.object(ImageClient, 'request', return_value=png()) as call:
            result = media.render(self.r, self.c)
            self.assertEqual(call.call_args.args[3], 'image/png')
        self.assertEqual(result['source_sha256'], item['sha256'])
        self.r['product_context']['model'] = 'HUAWEI MateBook Pro S'
        self.assertIsNone(media.match(self.r))

    def test_upload_rejects_invalid_bytes_and_unsafe_source(self):
        media = MediaProvider(Path(self.temp.name) / 'media')
        for payload in ({'model': 'PC', 'image_base64': 'not-base64'},
                        {'model': 'PC', 'image_base64': base64.b64encode(b'<script>x</script>').decode()},
                        {'model': 'PC', 'image_base64': base64.b64encode(png()).decode(), 'source_ref': 'javascript:alert(1)'}):
            with self.assertRaises(ContentError): register_reference(media, payload)
        self.assertFalse(list(Path(self.temp.name).rglob('ref-*')))

    def test_missing_ai_reference_fails_before_calling_copy_model(self):
        svc = ContentService(self.temp.name)
        try:
            self.r['product_context']['model'] = 'unknown model'
            self.r['copy_mode'] = 'llm'
            with patch.object(svc.copy_provider, 'generate') as call:
                with self.assertRaises(ContentError) as caught: svc.start(self.r)
                self.assertEqual(caught.exception.code, 'IMAGE_GENERATION_DISABLED')
                call.assert_not_called()
        finally: svc.shutdown()

    def test_timeout_is_distinguished_from_network_failure(self):
        client = ImageClient()
        for error, code in ((TimeoutError(), 'IMAGE_TIMEOUT'), (URLError('DNS failure details'), 'IMAGE_CONNECTION')):
            with patch.object(client.opener, 'open', side_effect=error):
                with self.assertRaises(ContentError) as caught: client.request(b'source', 'prompt', '1024x1536')
                self.assertEqual(caught.exception.code, code)
                self.assertNotIn('DNS', caught.exception.message)

    def test_jpeg_upload_accepts_existing_original(self):
        raw = (ROOT / 'ui/assets/content/matebook-pro-s-front.jpg').read_bytes()
        ext, mime, width, height = image_info(raw)
        self.assertEqual((ext, mime), ('jpg', 'image/jpeg'))
        self.assertGreater(width, 100)
        self.assertGreater(height, 100)
