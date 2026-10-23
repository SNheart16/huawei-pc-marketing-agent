"""B acceptance: real local renderer/storage + controlled A/LLM boundaries, no paid API calls."""
from copy import deepcopy
import http.client
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
from content_b import http as content_http
from content_b.contracts import ContentError, normalize
from content_b.providers import CopyProvider, MediaProvider, FactCheckAdapter, ROOT
from content_b.service import ContentService

EXAMPLES = json.loads((ROOT / "content_b/examples.json").read_text(encoding="utf-8"))
# These are regression fixtures for the existing deterministic SVG mode.
# The current fixed-material default is covered separately in test_pregenerated.py.
for example in EXAMPLES:
    example["request"]["image_mode"] = "layout"


class PassedChecker:
    def check(self, payload):
        return {"status": "passed", "content_hash": payload["content_hash"], "coverage": "complete", "claims": [],
                "verified_image_ids": [i["image_id"] for i in payload["images"]]}


class ContentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.s = ContentService(self.temp.name)
        self.request = deepcopy(EXAMPLES[0]["request"])

    def tearDown(self):
        self.s.shutdown()
        self.temp.cleanup()

    def wait(self, job):
        end = time.monotonic() + 5
        while job["status"] not in ("completed", "failed"):
            self.assertLess(time.monotonic(), end)
            time.sleep(.01)
            job = self.s.get_job(job["job_id"])
        return job

    def generate(self, request=None):
        job = self.wait(self.s.start(request or self.request))
        self.assertEqual(job["status"], "completed", job)
        return self.s.store.get(job["asset_id"])

    def test_complete_strategy_real_svg_and_pending_check(self):
        a = self.generate()
        self.assertEqual(len(a["images"]), 2)
        self.assertEqual(a["copy"]["cta"], "")
        self.assertFalse(a["can_publish"])
        self.assertEqual(a["fact_check_status"], "pending")
        for image in a["images"]:
            path = self.s.media.media_dir / (image["image_id"] + ".svg")
            self.assertTrue(path.is_file())
        svg = next(self.s.media.media_dir.glob('*.svg')).read_text(encoding="utf-8")
        self.assertIn('<svg', svg)
        states = [x["status"] for x in self.s.get_job(next(iter(self.s.jobs)))["events"]]
        self.assertEqual(states, ["pending", "generating_copy", "generating_images", "checking", "completed"])

    def test_distinct_audiences_and_platform_limits(self):
        values = [self.generate(deepcopy(e["request"]))["copy"]["body"] for e in EXAMPLES]
        self.assertEqual(len(set(values)), 3)
        r = deepcopy(self.request); r["platform"] = "门店海报"
        a = self.generate(r)
        self.assertLessEqual(len(a["copy"]["body"]), 300)

    def test_missing_model_does_not_invent_product_or_parameters(self):
        self.request["product_context"] = {"model": "", "facts": []}
        a = self.generate()
        self.assertEqual(a["images"][0]["source_type"], "editorial_card")
        self.assertNotIn("GB", a["copy"]["body"])
        self.assertFalse(a["images"][0]["product_model"])

    def test_fact_filter_excludes_conflicts_wrong_models_missing_sources_and_expired(self):
        valid = {"fact_id":"ok","claim":"已核实特点","source_ref":"official-doc","status":"supported","product_model":"HUAWEI MateBook Pro S"}
        self.request["product_context"]["facts"] = [valid, {**valid,"fact_id":"bad","status":"conflicting"}, {**valid,"fact_id":"expired","valid_until":"2000-01-01T00:00:00Z"}, {**valid,"fact_id":"wrong","product_model":"MateBook 14"}, {**valid,"fact_id":"none","source_ref":""}]
        request = normalize(self.request)
        self.assertEqual([f["fact_id"] for f in request["product_context"]["facts"]], ["ok"])
        self.assertEqual(len(request["excluded_facts"]), 4)

    def test_edit_then_replace_preserves_copy_and_other_images(self):
        a = self.generate()
        a = self.s.mutate(a["asset_id"], {"expected_version":a["version"],"copy":{"body":"我手写的文案，必须保留。"}})
        before = deepcopy(a)
        a = self.s.mutate(a["asset_id"], {"expected_version":a["version"],"replacement":{"image_id":a["images"][0]["image_id"],"catalog_id":"pro-s-angle"}})
        self.assertEqual(a["copy"], before["copy"])
        self.assertEqual(a["images"][1:], before["images"][1:])
        self.assertNotEqual(a["images"][0]["image_id"], before["images"][0]["image_id"])

    def test_only_copy_regeneration_keeps_images_byte_for_byte(self):
        a = self.generate(); images = deepcopy(a["images"])
        job = self.wait(self.s.start({"asset_id":a["asset_id"],"expected_version":a["version"],"scope":"copy"},True))
        b = self.s.store.get(job["asset_id"])
        self.assertEqual(images,b["images"])
        self.assertNotEqual(a["copy"]["body"],b["copy"]["body"])

    def test_only_images_regeneration_keeps_manual_copy(self):
        a=self.generate()
        a=self.s.mutate(a["asset_id"],{"expected_version":a["version"],"copy":{"body":"手动编辑正文"}})
        job=self.wait(self.s.start({"asset_id":a["asset_id"],"expected_version":a["version"],"scope":"images","art_direction":"warm"},True))
        b=self.s.store.get(job["asset_id"])
        self.assertEqual(a["copy"],b["copy"])
        self.assertNotEqual(a["images"][0]["image_id"],b["images"][0]["image_id"])

    def test_image_scope_ignores_copy_mode_change_and_requires_resave(self):
        a = self.generate()
        a = self.s.mutate(a['asset_id'], {'expected_version': a['version']}, 'save')
        job = self.wait(self.s.start({'asset_id': a['asset_id'], 'expected_version': a['version'], 'scope': 'images', 'copy_mode': 'llm'}, True))
        b = self.s.store.get(job['asset_id'])
        self.assertEqual(a['copy'], b['copy'])
        self.assertEqual(b['generation_mode'], 'assembly')
        self.assertFalse(b['saved'])

    def test_failed_regeneration_preserves_version(self):
        a=self.generate()
        with patch.object(self.s.media,"render",side_effect=RuntimeError("failure")):
            job=self.wait(self.s.start({"asset_id":a["asset_id"],"expected_version":a["version"],"scope":"images"},True))
        self.assertEqual(job["status"],"failed")
        self.assertEqual(self.s.store.get(a["asset_id"]),a)

    def test_regenerating_second_image_preserves_role_and_cover(self):
        a=self.generate()
        job=self.wait(self.s.start({"asset_id":a["asset_id"],"expected_version":a["version"],"scope":"image","image_id":a["images"][1]["image_id"]},True))
        b=self.s.store.get(job["asset_id"])
        self.assertEqual(a["images"][0],b["images"][0])
        self.assertEqual(b["images"][1]["role"],"场景清单")
        self.assertEqual(a["copy"],b["copy"])

    def test_llm_failure_is_not_replaced_with_assembly(self):
        from src.llm_client import LLMClientError
        self.request["copy_mode"]="llm"
        with patch("src.llm_client.LLMClient",side_effect=LLMClientError("Missing environment configuration: LLM_API_KEY")):
            job=self.wait(self.s.start(self.request))
        self.assertEqual(job["status"],"failed")
        self.assertEqual(job["error"]["code"],"MODEL_UNAVAILABLE")
        self.assertIsNone(job["asset_id"])

    def test_llm_receives_full_strategy_and_bounded_quality_repair(self):
        self.request["copy_mode"]="llm"
        with patch("src.llm_client.LLMClient") as client:
            client.return_value.generate_json.return_value={"title":"标题","body":"最强性能","cta":"","hashtags":[]}
            job=self.wait(self.s.start(self.request))
            self.assertEqual(client.return_value.generate_json.call_count,2)
            payload=client.return_value.generate_json.call_args.args[1]
            self.assertIn("audience_need",payload["confirmed_strategy"])
            self.assertIn("product_context",payload)
        self.assertEqual(job["error"]["code"],"QUALITY_FAILED")

    def test_initial_partial_image_failure_keeps_copy_and_successful_image(self):
        render=self.s.media.render
        def failing(request,copy,index):
            if index==1: raise RuntimeError()
            return render(request,copy,index)
        with patch.object(self.s.media,"render",side_effect=failing):
            a=self.generate()
        self.assertEqual(a["status"],"partial")
        self.assertEqual(len(a["images"]),1)
        self.assertTrue(a["copy"]["body"])
        self.assertFalse(a["can_publish"])

    def test_blocked_checker_never_makes_publishable(self):
        with patch.object(self.s.checker,"check",return_value={"status":"blocked","claims":[{"claim":"不实参数","status":"unsupported"}]}):
            a=self.generate()
        self.assertFalse(a["can_publish"])
        self.assertEqual(a["fact_check_status"],"blocked")
        with self.assertRaises(ContentError):
            self.s.mutate(a["asset_id"],{"expected_version":a["version"],"publish":True},"save")

    def test_passed_text_does_not_bypass_image_rights(self):
        self.s.checker=PassedChecker()
        a=self.generate()
        self.assertEqual(a["fact_check_status"],"passed")
        self.assertFalse(a["can_publish"])

    def test_edit_invalidates_prior_check_and_preserves_history(self):
        self.s.checker=PassedChecker(); a=self.generate()
        b=self.s.mutate(a["asset_id"],{"expected_version":a["version"],"copy":{"title":"新的标题"}})
        self.assertEqual(b["fact_check_status"],"pending")
        self.assertNotEqual(a["content_hash"],b["content_hash"])
        restored=self.s.mutate(a["asset_id"],{"expected_version":b["version"],"version":1},"restore")
        self.assertEqual(restored["copy"],a["copy"])
        self.assertEqual(restored["parent_version"],b["version"])
        self.assertEqual(restored["fact_check_status"],"pending")

    def test_save_restart_and_task_isolation(self):
        a=self.generate(); self.request["task_id"]="other-task"; b=self.generate()
        a=self.s.mutate(a["asset_id"],{"expected_version":a["version"]},"save")
        self.assertEqual([x["asset_id"] for x in self.s.store.list()], [a["asset_id"]])
        second=ContentService(self.temp.name)
        try:self.assertEqual(second.store.get(a["asset_id"])["copy"],a["copy"])
        finally:second.shutdown()
        self.s.delete(a["asset_id"],{"expected_version":a["version"]})
        self.assertEqual(self.s.store.get(b["asset_id"]),b)
        self.assertTrue((ROOT/'ui/assets/content/matebook-pro-s-front.jpg').exists())

    def test_stale_patch_and_idempotency_conflict(self):
        self.request["idempotency_key"]="one"
        job=self.s.start(self.request); duplicate=self.s.start(self.request)
        self.assertEqual(job["job_id"],duplicate["job_id"])
        self.wait(job)
        bad=deepcopy(self.request);bad["platform"]="公众号"
        with self.assertRaises(ContentError) as caught:self.s.start(bad)
        self.assertEqual(caught.exception.code,"IDEMPOTENCY_CONFLICT")
        a=self.s.store.get(self.s.get_job(job["job_id"])["asset_id"])
        self.s.mutate(a["asset_id"],{"expected_version":1,"copy":{"title":"新的标题"}})
        with self.assertRaises(ContentError):self.s.mutate(a["asset_id"],{"expected_version":1,"copy":{"title":"过时标题"}})

    def test_concurrent_regeneration_rejects_edits_and_duplicate_operation(self):
        a=self.generate(); started=threading.Event();release=threading.Event()
        original=self.s.copy_provider.generate
        def slow(*args):started.set();release.wait(3);return original(*args)
        with patch.object(self.s.copy_provider,"generate",side_effect=slow):
            job=self.s.start({"asset_id":a["asset_id"],"expected_version":1,"scope":"copy"},True)
            self.assertTrue(started.wait(1))
            try:
                with self.assertRaises(ContentError) as error:self.s.mutate(a["asset_id"],{"expected_version":1,"copy":{"title":"冲突编辑"}})
                self.assertEqual(error.exception.code,"BUSY")
                with self.assertRaises(ContentError):self.s.start({"asset_id":a["asset_id"],"expected_version":1,"scope":"copy"},True)
            finally:release.set()
            self.wait(job)

    def test_checker_contract_hash_coverage_and_unsupported_claims(self):
        payload={"content_hash":"current"}
        with self.assertRaises(ContentError):FactCheckAdapter.validate({"status":"passed","content_hash":"old","claims":[]},payload)
        result=FactCheckAdapter.validate({"status":"passed","content_hash":"current","claims":[]},payload)
        self.assertEqual(result["status"],"pending")
        result=FactCheckAdapter.validate({"status":"passed","content_hash":"current","coverage":"complete","claims":[{"status":"unsupported"}]},payload)
        self.assertEqual(result["status"],"blocked")

    def test_risky_manual_copy_is_not_publishable(self):
        self.s.checker=PassedChecker(); a=self.generate()
        a=self.s.mutate(a["asset_id"],{"expected_version":1,"copy":{"body":"续航99小时，最强性能。"}})
        a=self.s.validate(a["asset_id"],{"expected_version":a["version"]})
        self.assertEqual(a["fact_check_status"],"blocked")
        self.assertTrue(a["quality_issues"])

    def test_invalid_input_and_model_mismatch(self):
        self.request["confirmed"]=False
        with self.assertRaises(ContentError):self.s.start(self.request)
        self.request["confirmed"]=True; a=self.generate()
        with self.assertRaises(ContentError):self.s.mutate(a["asset_id"],{"expected_version":1,"can_publish":True})
        with self.assertRaises(ContentError):self.s.mutate(a["asset_id"],{"expected_version":1,"replacement":{"image_id":a["images"][0]["image_id"],"catalog_id":"wrong-model"}})


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.s=ContentService(self.temp.name)
        self.patch=patch.object(content_http,"_service",self.s);self.patch.start()
        self.server=app.ThreadingHTTPServer(("127.0.0.1",0),app.Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.patch.stop();self.s.shutdown();self.temp.cleanup()

    def req(self,path,method="GET",payload=None,headers=None):
        conn=http.client.HTTPConnection("127.0.0.1",self.server.server_port,timeout=5)
        try:
            conn.request(method,path,json.dumps(payload).encode() if payload is not None else None,headers or {"Content-Type":"application/json"})
            response=conn.getresponse();return response.status,response.read(),dict(response.getheaders())
        finally:conn.close()

    def test_http_generate_poll_media_patch_save_export_delete(self):
        status,raw,_=self.req('/api/content/generate','POST',EXAMPLES[0]['request']);self.assertEqual(status,202)
        job=json.loads(raw)['data']
        for _ in range(100):
            status,raw,_=self.req('/api/content/jobs/'+job['job_id']);job=json.loads(raw)['data']
            if job['status'] in ('completed','failed'):break
            time.sleep(.01)
        self.assertEqual(job['status'],'completed',job)
        aid=job['asset_id'];_,raw,_=self.req('/api/content/'+aid);a=json.loads(raw)['data']
        status,svg,_=self.req(a['images'][0]['url']);self.assertEqual(status,200);self.assertIn(b'<svg',svg)
        status,raw,_=self.req('/api/content/'+aid,'PATCH',{'expected_version':1,'copy':{'body':'保存的正文'}})
        self.assertEqual(status,200);a=json.loads(raw)['data']
        status,raw,_=self.req('/api/content/save','POST',{'asset_id':aid,'expected_version':a['version']});a=json.loads(raw)['data'];self.assertEqual(status,200)
        status,blob,headers=self.req('/api/content/'+aid+'/export');self.assertEqual(status,200)
        with zipfile.ZipFile(io.BytesIO(blob)) as z:self.assertIn('fact-check-request.json',z.namelist());self.assertIn('保存的正文',z.read('copy.txt').decode())
        status,_,_=self.req('/api/content/'+aid,'DELETE',{'expected_version':a['version']});self.assertEqual(status,200)
        status,_,_=self.req('/api/content/'+aid);self.assertEqual(status,404)

    def test_cross_origin_write_and_invalid_inputs_are_rejected(self):
        status,_,_=self.req('/api/content/generate','POST',{}, {'Content-Type':'application/json','Origin':'https://untrusted.example'})
        self.assertEqual(status,403)
        status,raw,_=self.req('/api/content/generate','POST',[]);self.assertEqual(status,400)
        self.assertFalse(json.loads(raw)['success'])
        status,_,_=self.req('/api/content/media/../content.sqlite3');self.assertEqual(status,404)

    def test_png_media_and_export_keep_actual_generated_file(self):
        from test_content_image import png
        request = deepcopy(EXAMPLES[0]['request']); request.update(image_count=1)
        job = self.s.start(request)
        for _ in range(200):
            job = self.s.get_job(job['job_id'])
            if job['status'] in ('completed', 'failed'): break
            time.sleep(.01)
        a = self.s.store.get(job['asset_id'])
        image = a['images'][0]
        image.update(render_method='image_api_reference', is_generated=True, url=image['url'].replace('.svg', '.png'))
        (self.s.media.media_dir / (image['image_id'] + '.png')).write_bytes(png())
        a = self.s.store.put(a, a['version'])
        status, raw, headers = self.req(image['url'])
        self.assertEqual(status, 200); self.assertEqual(raw, png()); self.assertEqual(headers['Content-Type'], 'image/png')
        status, raw, _ = self.req('/api/content/' + a['asset_id'] + '/export')
        self.assertEqual(status, 200)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            self.assertEqual(archive.read(image['image_id'] + '.png'), png())

    def test_reference_upload_is_persistent_accessible_and_not_a_fact(self):
        import base64
        from test_content_image import png
        status, raw, _ = self.req('/api/content/references', 'POST', {'model': 'PC', 'image_base64': base64.b64encode(png()).decode()})
        self.assertEqual(status, 201)
        item = json.loads(raw)['data']
        status, image, headers = self.req(item['url'])
        self.assertEqual(status, 200); self.assertEqual(image, png())
        status, raw, _ = self.req('/api/content/catalog?model=PC')
        self.assertEqual(json.loads(raw)['data'][0]['rights_status'], 'unconfirmed')


if __name__=='__main__':unittest.main()
