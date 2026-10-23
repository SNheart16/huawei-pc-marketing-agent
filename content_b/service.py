"""Durable, versioned content lifecycle, independent from A's decision workflow."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import threading
import uuid

from .contracts import ContentError, normalize, validate_copy, local_warnings, digest, now, text
from .providers import ROOT, CopyProvider, MediaProvider, FactCheckAdapter


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        with self.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS assets (id TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS versions (id TEXT, version INTEGER, value TEXT NOT NULL, PRIMARY KEY(id, version));
            CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, value TEXT NOT NULL);''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, asset_id):
        with self.connect() as db:
            row = db.execute("SELECT value FROM assets WHERE id=?", (asset_id,)).fetchone()
        if not row:
            raise ContentError("NOT_FOUND", "成果不存在或已删除。", 404)
        return json.loads(row[0])

    def put(self, value, expected=None):
        with self.lock, self.connect() as db:
            row = db.execute("SELECT value FROM assets WHERE id=?", (value["asset_id"],)).fetchone()
            current = json.loads(row[0]) if row else None
            if expected is not None and (not current or current["version"] != expected):
                raise ContentError("VERSION_CONFLICT", "成果已被其他操作修改，请重新读取最新版本。", 409)
            value = deepcopy(value)
            value["version"] = current["version"] + 1 if current else 1
            value["parent_version"] = current["version"] if current else None
            value["updated_at"] = now()
            encoded = json.dumps(value, ensure_ascii=False)
            db.execute("INSERT OR REPLACE INTO assets VALUES (?,?)", (value["asset_id"], encoded))
            db.execute("INSERT INTO versions VALUES (?,?,?)", (value["asset_id"], value["version"], encoded))
        return value

    def list(self, task_id=None):
        with self.connect() as db:
            values = [json.loads(row[0]) for row in db.execute("SELECT value FROM assets")]
        return sorted((x for x in values if x.get("saved") and (not task_id or x["task_id"] == task_id)), key=lambda x: x["updated_at"], reverse=True)

    def versions(self, asset_id):
        self.get(asset_id)
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT value FROM versions WHERE id=? ORDER BY version DESC", (asset_id,))]

    def delete(self, asset_id):
        self.get(asset_id)
        with self.lock, self.connect() as db:
            db.execute("DELETE FROM assets WHERE id=?", (asset_id,))
            db.execute("DELETE FROM versions WHERE id=?", (asset_id,))
        # Media is retained; never delete shared official sources or another task's files.

    def job(self, value):
        with self.lock, self.connect() as db:
            db.execute("INSERT OR REPLACE INTO jobs VALUES (?,?)", (value["job_id"], json.dumps(value, ensure_ascii=False)))

    def jobs(self):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT value FROM jobs")]


class ContentService:
    def __init__(self, data_dir=None, copy_provider=None, media_provider=None, checker=None):
        self.data_dir = Path(data_dir or ROOT / ".content-data")
        self.store = Store(self.data_dir / "content.sqlite3")
        self.copy_provider = copy_provider or CopyProvider()
        self.media = media_provider or MediaProvider(self.data_dir / "media")
        self.checker = checker or FactCheckAdapter()
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="content-b")
        self.active = set()
        self.jobs = {x["job_id"]: x for x in self.store.jobs()}
        for job in self.jobs.values():
            if job["status"] not in ("completed", "failed"):
                job.update(status="failed", error={"code": "SERVER_RESTARTED", "message": "服务重启中断了任务，已有成果保持不变，请重试。"})
                self.store.job(job)

    def shutdown(self):
        self.pool.shutdown(wait=True)

    def get_job(self, job_id):
        with self.lock:
            if job_id not in self.jobs:
                raise ContentError("NOT_FOUND", "生成任务不存在。", 404)
            return deepcopy(self.jobs[job_id])

    def stage(self, job_id, status, **extra):
        with self.lock:
            job = self.jobs[job_id]
            job.update(status=status, updated_at=now(), **extra)
            job["events"].append({"status": status, "at": now()})
            self.store.job(job)

    def start(self, payload, regenerate=False):
        if not isinstance(payload, dict):
            raise ContentError("INVALID_INPUT", "请求须为 JSON 对象。")
        previous = None
        if regenerate:
            previous = self.store.get(text(payload.get("asset_id", ""), "asset_id", 128, True))
            self.expected(previous, payload)
            request = deepcopy(previous["request"])
            scope = payload.get("scope")
            if scope not in ("all", "copy", "images", "image"):
                raise ContentError("INVALID_INPUT", "scope 必须为 all、copy、images 或 image。")
            if scope == "image" and not any(i["image_id"] == payload.get("image_id") for i in previous["images"]):
                raise ContentError("NOT_FOUND", "指定图片不存在。", 404)
            if payload.get("art_direction"):
                request["art_direction"] = payload["art_direction"]
            if scope in ("all", "copy") and "copy_mode" in payload:
                request["copy_mode"] = payload["copy_mode"]
            if scope in ("all", "images", "image") and "image_mode" in payload:
                request["image_mode"] = payload["image_mode"]
            if scope in ("all", "images", "image") and "reference_id" in payload:
                request['reference_id'] = payload['reference_id']
            request = normalize(request)
        else:
            request, scope = normalize(payload), "all"
        if request["image_mode"] == "ai_reference":
            raise ContentError("IMAGE_GENERATION_DISABLED", "本演示使用预生成素材，请选择配图；不调用生图服务。", 422)
        if request.get("a_binding") is not None:
            from .a_bridge import assert_current
            assert_current(request["a_binding"])
        if scope in ('all', 'images', 'image') and request['image_mode'] != 'pregenerated' and request.get('reference_id') and not self.media.match(request):
            raise ContentError('IMAGE_REFERENCE_REQUIRED', '所选原图不存在或与当前产品型号不一致，请重新选择。', 422)
        if scope in ('all', 'images', 'image') and request['image_mode'] == 'ai_reference':
            if not self.media.match(request):
                raise ContentError('IMAGE_REFERENCE_REQUIRED', '没有该型号的产品原图，请先上传对应型号的参考图，再生成 AI 海报。', 422)
        adjustment = text(payload.get("adjustment", ""), "adjustment", 1000)
        key = text(payload.get("idempotency_key", ""), "idempotency_key", 128)
        fingerprint = digest(payload)
        resource = previous["asset_id"] if previous else request["task_id"] + ":" + request["platform"]
        with self.lock:
            if key:
                for job in self.jobs.values():
                    if job.get("key") == key:
                        if job["fingerprint"] != fingerprint:
                            raise ContentError("IDEMPOTENCY_CONFLICT", "同一请求键不能用于不同内容。", 409)
                        return deepcopy(job)
            if resource in self.active:
                raise ContentError("BUSY", "当前成果正在处理，请等待本次操作完成。", 409)
            if len(self.active) >= 8:
                raise ContentError("QUEUE_FULL", "生成队列已满，请稍后重试。", 429)
            self.active.add(resource)
            job_id = "job-" + uuid.uuid4().hex
            job = {"job_id": job_id, "task_id": request["task_id"], "status": "pending", "asset_id": previous["asset_id"] if previous else None,
                   "events": [{"status": "pending", "at": now()}], "key": key, "fingerprint": fingerprint, "error": None, "created_at": now()}
            self.jobs[job_id] = job
            self.store.job(job)
            self.pool.submit(self.run, job_id, resource, request, previous, scope, adjustment, payload.get("image_id"))
            return deepcopy(job)

    def run(self, job_id, resource, request, previous, scope, adjustment, selected_image):
        try:
            asset = deepcopy(previous) if previous else {"asset_id": "asset-" + uuid.uuid4().hex, "task_id": request["task_id"], "strategy_id": request["strategy"]["strategy_id"], "created_at": now(), "saved": False, "images": [], "copy": {}}
            asset.update(request=request, platform=request["platform"], generation_mode=request["copy_mode"], errors=[], status="pending", saved=False)
            if scope in ("all", "copy"):
                self.stage(job_id, "generating_copy")
                asset["copy"] = self.copy_provider.generate(request, adjustment, asset.get("version", 0))
                asset["copy"] = validate_copy(asset["copy"], request)
            if scope in ("all", "images", "image"):
                self.stage(job_id, "generating_images")
                request["image_adjustment"] = adjustment
                request["image_revision"] = asset.get("version", 0)
                if request["image_mode"] == "pregenerated":
                    # Regeneration changes copy only; manually chosen material/order is retained.
                    selected_ids = ([image["image_id"] for image in previous["images"]]
                        if previous and previous["request"]["image_mode"] == "pregenerated" else None)
                    asset["images"] = self.media.selected(request, selected_ids)
                    available = sum(item["available"] for item in self.media.pregenerated(request["product_context"]["model"], request["platform"]))
                    asset["material_notice"] = ("待补充素材：当前没有匹配产品和平台的可用图片。" if not asset["images"]
                        else f"本平台可用 {available} 张预生成素材；" + ("素材不足 2 张，待补充；" if available < 2 else "")
                        + "图片型号、授权及视觉内容仍待确认。")
                else:
                    self.render_legacy_images(asset, request, previous, scope, selected_image)
            self.stage(job_id, "checking")
            self.check(asset)
            asset["status"] = "partial" if asset["errors"] or (request["image_mode"] == "pregenerated" and not asset["images"]) else "completed"
            asset["last_action"] = f"regenerate:{scope}" if previous else "generate"
            asset = self.store.put(asset, previous["version"] if previous else None)
            self.stage(job_id, "completed", asset_id=asset["asset_id"], version=asset["version"], partial=asset["status"] == "partial")
        except Exception as exc:
            err = exc if isinstance(exc, ContentError) else ContentError("GENERATION_FAILED", "生成未完成，原稿已保留，请检查配置后重试。", 500)
            self.stage(job_id, "failed", error={"code": err.code, "message": err.message})
        finally:
            with self.lock:
                self.active.discard(resource)

    def render_legacy_images(self, asset, request, previous, scope, selected_image):
        generated = []
        count = len(previous["images"]) if previous and scope == "images" else request["image_count"]
        if scope == "image":
            count = 1
        for index in range(count):
            try:
                render_index = next(i for i, image in enumerate(previous["images"]) if image["image_id"] == selected_image) if scope == "image" else index
                generated.append(self.media.render(request, asset["copy"], render_index))
            except Exception as exc:
                asset["errors"].append({"code": exc.code if isinstance(exc, ContentError) else "IMAGE_FAILED", "index": index,
                    "message": exc.message if isinstance(exc, ContentError) else "该图片未完成，已有内容已保留。"})
        if previous and asset["errors"]:
            raise ContentError(asset['errors'][0]['code'], asset["errors"][0]["message"] + " 当前图文保持原版本。", 502)
        if scope == "image":
            asset["images"] = [generated[0] if i["image_id"] == selected_image else i for i in asset["images"]]
        else:
            asset["images"] = generated

    @staticmethod
    def expected(asset, payload):
        value = payload.get("expected_version")
        if type(value) is not int or value != asset["version"]:
            raise ContentError("VERSION_CONFLICT", "请传入最新 expected_version，避免覆盖其他修改。", 409)

    def check_payload(self, asset):
        request = asset["request"]
        payload = {"schema_version": "content-b/1.0", "asset_id": asset["asset_id"], "task_id": asset["task_id"], "strategy_id": asset["strategy_id"],
                   "copy": asset["copy"], "images": asset["images"], "strategy": request["strategy"],
                   "fact_references": request["product_context"]["facts"], "sources": list(dict.fromkeys(f["source_ref"] for f in request["product_context"]["facts"]))}
        if request.get("a_binding") is not None:
            payload["a_binding"] = deepcopy(request["a_binding"])
        payload["content_hash"] = digest(payload)
        return payload

    def check(self, asset):
        payload = self.check_payload(asset)
        asset["content_hash"] = payload["content_hash"]
        asset["quality_issues"] = local_warnings(asset["copy"], asset["request"])
        try:
            # Inspect current file identity before granting a result to these exact images.
            for image in asset["images"]:
                if image.get("render_method") == "pre_generated":
                    self.media.export_image(image)
            asset["fact_check"] = self.checker.check(payload)
        except ContentError as exc:
            asset["fact_check"] = {"status": "pending", "claims": [], "reason": exc.message, "error_code": exc.code}
        asset["fact_check_status"] = asset["fact_check"]["status"]
        asset["text_usable"] = asset["fact_check"].get("text_usable", False)
        if asset["quality_issues"]:
            asset["fact_check_status"] = "blocked"
            asset["text_usable"] = False
        asset["publish_blockers"] = list(asset["quality_issues"])
        if asset["fact_check_status"] != "passed":
            asset["publish_blockers"].append(asset["fact_check"].get("reason") or "最终事实核查尚未通过。")
        if not asset["images"]:
            asset["publish_blockers"].append("没有可用图片。")
        for image in asset["images"]:
            if image["rights_status"] not in ("approved", "owned"):
                asset["publish_blockers"].append("产品素材的商业使用授权尚未确认。")
            # A must attest to these exact image IDs, including text in the image.
            approved = asset["fact_check"].get("verified_image_ids", [])
            if image["image_id"] not in approved:
                asset["publish_blockers"].append("图片及图片内文字尚未完成最终核验。")
        if asset.get("errors"):
            asset["publish_blockers"].append("部分成果尚未生成成功。")
        asset["publish_blockers"] = list(dict.fromkeys(asset["publish_blockers"]))
        asset["can_publish"] = not asset["publish_blockers"]

    def invalidate(self, asset):
        asset["text_usable"] = False
        asset.update(saved=False, fact_check_status="pending", fact_check={"status": "pending", "claims": [], "reason": "内容已修改，需按当前版本重新核查。"}, can_publish=False,
                     publish_blockers=["内容已修改，请重新核查。"], quality_issues=local_warnings(asset["copy"], asset["request"]))
        asset["content_hash"] = self.check_payload(asset)["content_hash"]

    def mutate(self, asset_id, payload, operation="patch"):
        with self.lock:
            if asset_id in self.active:
                raise ContentError("BUSY", "当前成果正在生成或核查，请稍后操作。", 409)
            asset = self.store.get(asset_id)
            self.expected(asset, payload)
            expected = asset["version"]
            if operation == "patch":
                if set(payload) - {"expected_version", "copy", "image_order", "replacement", "remove_image_id", "selected_image_ids"}:
                    raise ContentError("IMMUTABLE_FIELD", "仅允许修改文案、图片顺序或指定图片。")
                if "copy" in payload:
                    if not isinstance(payload["copy"], dict) or set(payload["copy"]) - {"title", "body", "cta", "hashtags"}:
                        raise ContentError("INVALID_INPUT", "文案字段不合法。")
                    asset["copy"] = validate_copy({**asset["copy"], **payload["copy"]}, asset["request"])
                if "selected_image_ids" in payload:
                    if any(key in payload for key in ("replacement", "remove_image_id", "image_order")):
                        raise ContentError("INVALID_INPUT", "selected_image_ids 已包含完整顺序，请勿同时传其他图片修改字段。")
                    asset["images"] = self.media.selected(asset["request"], payload["selected_image_ids"])
                    asset["request"]["image_mode"] = "pregenerated"
                if "image_order" in payload:
                    order = payload["image_order"]
                    current = {i["image_id"]: i for i in asset["images"]}
                    if not isinstance(order, list) or any(not isinstance(i, str) for i in order) or len(order) != len(current) or set(order) != set(current):
                        raise ContentError("INVALID_INPUT", "排序必须包含每张现有图片且不重复。")
                    asset["images"] = [current[i] for i in order]
                if "replacement" in payload:
                    replacement = payload["replacement"]
                    if not isinstance(replacement, dict):
                        raise ContentError("INVALID_INPUT", "replacement 须为对象。")
                    target = next((i for i,x in enumerate(asset["images"]) if x["image_id"] == replacement.get("image_id")), None)
                    if target is None:
                        raise ContentError("NOT_FOUND", "图片不存在。", 404)
                    catalog_id = replacement.get("catalog_id")
                    if asset["request"]["image_mode"] == "pregenerated":
                        if catalog_id in [image["image_id"] for index, image in enumerate(asset["images"]) if index != target]:
                            raise ContentError("INVALID_INPUT", "同一素材不能重复选择。")
                        asset["images"][target] = self.media.selected(asset["request"], [catalog_id])[0]
                    else:
                        if not isinstance(catalog_id, str) or not self.media.match(asset["request"], catalog_id):
                            raise ContentError("MODEL_MISMATCH", "仅可替换为相同型号的已登记素材。", 422)
                        asset["images"][target] = self.media.render(asset["request"], asset["copy"], target, catalog_id)
                if "remove_image_id" in payload:
                    if len(asset["images"]) <= 1 and asset["request"]["image_mode"] != "pregenerated":
                        raise ContentError("LAST_IMAGE", "请至少保留一张图片。", 422)
                    if payload["remove_image_id"] not in [i["image_id"] for i in asset["images"]]:
                        raise ContentError("NOT_FOUND", "图片不存在。", 404)
                    asset["images"] = [i for i in asset["images"] if i["image_id"] != payload["remove_image_id"]]
                self.invalidate(asset)
            elif operation == "save":
                if payload.get("publish"):
                    self.check(asset)
                    if not asset["can_publish"]:
                        raise ContentError("PUBLISH_BLOCKED", "核查或素材授权未通过，仅可保存审核草稿。", 422)
                asset.update(saved=True, saved_at=now())
            elif operation == "restore":
                old = next((x for x in self.store.versions(asset_id) if x["version"] == payload.get("version")), None)
                if old is None:
                    raise ContentError("NOT_FOUND", "历史版本不存在。", 404)
                asset = old
                self.invalidate(asset)
            else:
                raise ContentError("INVALID_INPUT", "未知修改类型。")
            asset["last_action"] = operation
            return self.store.put(asset, expected)

    def validate(self, asset_id, payload):
        with self.lock:
            if asset_id in self.active:
                raise ContentError("BUSY", "当前成果正在处理。", 409)
            asset = self.store.get(asset_id)
            self.expected(asset, payload)
            self.active.add(asset_id)
        try:
            self.check(asset)
            asset["last_action"] = "validate"
            return self.store.put(asset, asset["version"])
        finally:
            with self.lock:
                self.active.discard(asset_id)

    def delete(self, asset_id, payload):
        with self.lock:
            if asset_id in self.active:
                raise ContentError("BUSY", "生成中的成果不能删除。", 409)
            self.expected(self.store.get(asset_id), payload)
            self.store.delete(asset_id)
            return {"deleted": True, "asset_id": asset_id}
