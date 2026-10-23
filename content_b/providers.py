"""Adapters: existing LLM client, immutable local media, and member A HTTP API."""
import base64
from copy import deepcopy
import html
import hashlib
import json
import os
from pathlib import Path
import re
import textwrap
from urllib.parse import urlsplit, unquote
from urllib.request import Request, build_opener, HTTPRedirectHandler
import uuid

from .contracts import ContentError, digest, now, validate_copy, local_warnings

ROOT = Path(__file__).resolve().parents[1]


class CopyProvider:
    def generate(self, request, adjustment="", revision=0):
        s = request["strategy"]
        if request["copy_mode"] == "llm":
            from src.llm_client import LLMClient, LLMClientError
            prompt = (ROOT / "prompts" / "content-b.md").read_text(encoding="utf-8")
            payload = {"confirmed_strategy": s, "product_context": request["product_context"], "platform": request["platform"],
                       "length_limits": request["limits"], "adjustment": adjustment, "revision": revision}
            try:
                client = LLMClient()
                for attempt in range(2):
                    raw = client.generate_json(prompt, payload)
                    try:
                        result = validate_copy(raw, request)
                    except ContentError as exc:
                        payload["repair_requirements"] = [exc.message]
                        continue
                    issues = local_warnings(result, request)
                    if not issues:
                        return result
                    payload["repair_requirements"] = issues
                raise ContentError("QUALITY_FAILED", "有限修正后仍含风险表达，请调整策略或文案。", 422)
            except LLMClientError as exc:
                raise ContentError("MODEL_UNAVAILABLE", str(exc), 503) from None
        # Explicit no-model mode: only arrange supplied strategy/evidence, never fabricate an AI run.
        facts = request["product_context"]["facts"]
        outline = s["content_outline"] or [s["audience_need"]]
        blocks = [s["core_message"], *outline]
        if revision % 2:
            blocks = [*outline, s["core_message"]]
        if facts:
            blocks += ["资料中可以确认的内容：\n" + "\n".join(f["claim"] for f in facts)]
        body = "\n\n".join(dict.fromkeys(x for x in blocks if x))
        if request["platform"] in ("公众号", "微信公众号"):
            body = s["audience_need"] + "\n\n" + body
        if "简" in adjustment:
            body = "\n\n".join(blocks[:2])
        if len(body) > request["limits"]["body"]:
            # Keep complete sentences/blocks, never cut an evidence qualification in half.
            kept = []
            for block in body.split("\n\n"):
                if len("\n\n".join([*kept, block])) <= request["limits"]["body"]:
                    kept.append(block)
            if not kept:
                raise ContentError("COPY_TOO_LONG", "完整段落超过平台长度，请精简策略或使用模型模式。", 422)
            body = "\n\n".join(kept)
        copy = {"title": s["topic"][:request["limits"]["title"]], "body": body, "cta": s["cta"], "hashtags": []}
        return validate_copy(copy, request)


class MediaProvider:
    def __init__(self, media_dir=None, catalog_path=None, pregenerated_path=None):
        self.media_dir = Path(media_dir or ROOT / ".content-data" / "media")
        self.media_dir.mkdir(parents=True, exist_ok=True)
        path = Path(catalog_path or ROOT / "content_b" / "catalog.json")
        self.catalog = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        self.pregenerated_path = Path(pregenerated_path or ROOT / "ui" / "assets" / "pregenerated" / "manifest.json")

    @staticmethod
    def platform_key(platform):
        return {"微信公众号": "公众号", "门店朋友圈": "微信朋友圈"}.get(platform, platform)

    @staticmethod
    def model_key(model):
        return re.sub(r"[\s\-]+", "", model).lower().removeprefix("huawei")

    @classmethod
    def model_matches(cls, item, model):
        actual, selected = cls.model_key(item.get("product_model", "")), cls.model_key(model)
        if not actual or not selected:
            return False
        if actual == selected:
            return True
        # A broad family label is only a suitability suggestion, never exact-model proof.
        return (item.get("model_match_scope") == "family" and actual == "matebookxpro"
                and selected.startswith("matebookxpro") and not re.search(r"matebook(?:14|16)|2021", selected))

    @staticmethod
    def pregenerated_source_path(url):
        parsed = urlsplit(url) if isinstance(url, str) else None
        if (not parsed or parsed.scheme or parsed.netloc or parsed.query or parsed.fragment
                or not parsed.path.startswith("/assets/pregenerated/") or "\\" in parsed.path):
            raise ContentError("INVALID_MATERIAL_PATH", "预生成素材必须使用本站素材目录 URL。", 422)
        base = (ROOT / "ui" / "assets" / "pregenerated").resolve()
        path = (ROOT / "ui" / unquote(parsed.path).lstrip("/")).resolve()
        if not path.is_relative_to(base) or path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
            raise ContentError("INVALID_MATERIAL_PATH", "素材路径或文件类型不合法。", 422)
        return path

    def pregenerated(self, model="", platform=""):
        if not self.pregenerated_path.is_file():
            return []
        try:
            manifest = json.loads(self.pregenerated_path.read_text(encoding="utf-8-sig"))
            entries = manifest["assets"]
            if not isinstance(entries, list):
                raise ValueError()
            result, ids = [], set()
            for entry in entries:
                item = deepcopy(entry)
                material_id = item["material_id"]
                if not isinstance(material_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", material_id) or material_id in ids:
                    raise ValueError()
                ids.add(material_id)
                path = self.pregenerated_source_path(item["url"])
                if model and not self.model_matches(item, model):
                    continue
                if platform and self.platform_key(item.get("platform")) != self.platform_key(platform):
                    continue
                item.update(catalog_id=material_id, source_type="pre_generated", visual_check_status="unknown",
                            available=path.is_file(), exact_model_verified=False)
                item["rights_status"] = "unconfirmed"
                item["model_limitations"] = "用户提供素材的型号适用性未独立核实；系列匹配不证明具体配置版本一致。"
                result.append(item)
            return result
        except ContentError:
            raise
        except (OSError, ValueError, KeyError, TypeError):
            raise ContentError("MATERIAL_MANIFEST_INVALID", "预生成素材清单无法读取或结构不合法。", 503) from None

    def selected(self, request, material_ids=None):
        candidates = self.pregenerated(request["product_context"]["model"], request["platform"])
        if material_ids is None:
            topic = request["strategy"]["topic"]
            candidates.sort(key=lambda item: not (item.get("theme") and item["theme"] in topic))
            chosen = [item for item in candidates if item["available"]][:request["image_count"]]
        else:
            if (not isinstance(material_ids, list) or len(material_ids) > 4
                    or any(not isinstance(item, str) for item in material_ids) or len(set(material_ids)) != len(material_ids)):
                raise ContentError("INVALID_INPUT", "selected_image_ids 须为最多 4 个不重复素材 ID，允许空数组。")
            catalog = {item["material_id"]: item for item in candidates}
            if any(material_id not in catalog for material_id in material_ids):
                raise ContentError("MODEL_MISMATCH", "所选素材不存在或不适用于当前产品及平台。", 422)
            chosen = [catalog[material_id] for material_id in material_ids]
            if any(not item["available"] for item in chosen):
                raise ContentError("IMAGE_MISSING", "所选素材文件不存在，请补充素材或取消选择。", 422)
        images = []
        for item in chosen:
            path = self.pregenerated_source_path(item["url"])
            images.append({**item, "image_id": item["material_id"], "alt": item.get("theme", "预生成素材"),
                "role": "预生成素材", "source_ref": item["url"], "reference_url": item["url"],
                "is_generated": False, "generation_prompt": None, "render_method": "pre_generated",
                "text_content": item.get("text_content", []), "text_content_status": "not_ocr_verified",
                "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "task_id": request["task_id"],
                "strategy_id": request["strategy"]["strategy_id"], "created_at": now()})
        return images

    def export_image(self, image):
        if image.get("render_method") == "pre_generated":
            item = next((item for item in self.pregenerated() if item["material_id"] == image["image_id"]), None)
            if not item or item["url"] != image["url"]:
                raise ContentError("IMAGE_MISSING", "素材登记已变化，请重新选择图片。", 422)
            path = self.pregenerated_source_path(item["url"])
            if not path.is_file():
                raise ContentError("IMAGE_MISSING", "素材文件不存在，请补充后再下载。", 422)
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != image.get("source_sha256"):
                raise ContentError("IMAGE_CHANGED", "素材文件已变化，请重新选择并核查当前图片。", 409)
            return image["image_id"] + path.suffix.lower(), raw
        name = image["image_id"] + (".png" if image.get("render_method") == "image_api_reference" else ".svg")
        path = self.media_dir / name
        if not path.is_file():
            raise ContentError("IMAGE_MISSING", "导出图片已失效，请重新选择后再导出。", 422)
        return name, path.read_bytes()

    def list(self, model="", platform=""):
        items = list(self.catalog)
        for path in (self.media_dir.parent / 'references').glob('ref-*.json'):
            items.append(json.loads(path.read_text(encoding='utf-8')))
        return [deepcopy(x) for x in items if not platform and (not model or x["product_model"] == model)] + self.pregenerated(model, platform)

    def source_path(self, source):
        if source.get('source_type') == 'user_reference':
            return self.media_dir.parent / 'references' / source['url'].rsplit('/', 1)[1]
        return ROOT / 'ui' / source['url'].lstrip('/')

    def match(self, request, catalog_id=None):
        model = request["product_context"]["model"]
        candidates = [x for x in self.list(model) if x["product_model"] == model
                      and x.get("purpose") != "style_reference" and x.get("source_type") != "pre_generated"]
        if request.get('reference_id') and not catalog_id:
            candidates = [x for x in candidates if x['catalog_id'] == request['reference_id']]
        if catalog_id:
            candidates = [x for x in candidates if x["catalog_id"] == catalog_id]
        candidates.sort(key=lambda x: x.get("rights_status") != "approved")
        if not candidates:
            return None
        return candidates[0]

    def render(self, request, copy, index=0, catalog_id=None):
        if request.get("image_mode") == "ai_reference" and catalog_id is None:
            from .image_client import ImageClient
            return ImageClient().render(self, request, copy, index)
        source = self.match(request, catalog_id)
        if index > 0 and not catalog_id:
            source = None
        image_id = "img-" + uuid.uuid4().hex
        direction = request["art_direction"]
        width, height = (1200, 1600) if request["platform"] == "小红书" else (1200, 1200)
        if request["platform"] in ("公众号", "微信公众号"):
            width, height = 1600, 900
        # A real byte-preserving product photo, or a clearly labelled typographic card.
        photo = ""
        if source:
            path = self.source_path(source)
            if not path.is_file():
                raise ContentError("IMAGE_MISSING", "素材文件已失效，请选择其他图片。", 422)
            encoded = base64.b64encode(path.read_bytes()).decode()
            photo_mime = source.get('mime_type', 'image/jpeg')
            if source["catalog_id"] == "pro-s-front":
                photo = f'<svg x="{width*.04}" y="{height*.29}" width="{width*.92}" height="{height*.46}" viewBox="0 270 1260 820"><image href="data:image/jpeg;base64,{encoded}" width="1260" height="1360"/></svg>'
            else:
                photo = f'<image href="data:{photo_mime};base64,{encoded}" x="{width*.04}" y="{height*.25}" width="{width*.92}" height="{height*.54}" preserveAspectRatio="xMidYMid meet"/>'
        palette = {"editorial": ("#f6f6f8", "#24272d", "#a92c3c"), "warm": ("#eee6da", "#3c342e", "#916c40"), "minimal": ("#eaf0f2", "#172c38", "#325d6d")}
        bg, ink, accent = palette[direction]
        title = copy["title"] if index == 0 else ["", "把需要，写成清单", "先核对，再做决定"][index]
        title = title[:40]
        title_lines = textwrap.wrap(title, 15 if height > width else 22)
        title_svg = "".join(f'<text x="{width*.07}" y="{height*.14 + i*height*.05}" font-size="{height*.038}" font-weight="600">{html.escape(t)}</text>' for i, t in enumerate(title_lines))
        model = request["product_context"]["model"] or "从你的实际用途开始"
        caption = "原始产品素材排版 · 授权与最终内容待审核" if source else "选购问题卡 · 未使用指定型号产品图"
        extra_text = []
        if not source:
            questions = request["strategy"]["content_outline"] or [request["strategy"]["audience_need"], request["strategy"]["core_message"]]
            cards = []
            for n, question in enumerate(questions[:3]):
                # Each card has one distinct editorial role; raw evidence is kept in the sidecar.
                safe_question = question[:70]
                extra_text.append(safe_question)
                top = height * (.30 + n * .15)
                lines = textwrap.wrap(safe_question, 26 if height > width else 38)[:3]
                cards.append(f'<text x="{width*.07}" y="{top}" font-size="24" fill="{accent}">0{n+1}</text>')
                cards.extend(f'<text x="{width*.14}" y="{top+j*height*.027}" font-size="{height*.019}">{html.escape(line)}</text>' for j,line in enumerate(lines))
            photo = "".join(cards)
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<rect width="100%" height="100%" fill="{bg}"/><g font-family="Microsoft YaHei, PingFang SC, Arial, sans-serif" fill="{ink}">
<text x="{width*.07}" y="{height*.055}" font-size="22" letter-spacing="5">HUAWEI PC / NOTES</text><text x="{width*.90}" y="{height*.055}" font-size="22">0{index+1}</text>
{title_svg}{photo}<rect x="{width*.07}" y="{height*.81}" width="44" height="5" fill="{accent}"/>
<text x="{width*.07}" y="{height*.86}" font-size="{width*.025}">{html.escape(model[:50])}</text>
<text x="{width*.07}" y="{height*.90}" font-size="{width*.018}" fill="{accent}">{html.escape(request['strategy']['audience'][:36])} · {html.escape(['主题封面','场景清单','选购参考'][index])}</text>
<text x="{width*.07}" y="{height*.96}" font-size="17" fill="#666">{caption}</text></g></svg>'''
        target = self.media_dir / f"{image_id}.svg"
        target.write_text(svg, encoding="utf-8")
        return {"image_id": image_id, "url": f"/api/content/media/{image_id}.svg", "alt": title,
                "role": ["主题封面", "场景清单", "选购参考"][index], "source_type": ("user_asset_composite" if source.get('source_type') == 'user_reference' else "official_asset_composite") if source else "editorial_card",
                "source_ref": source["source_ref"] if source else None, "catalog_id": source["catalog_id"] if source else None,
                "reference_url": source['url'] if source else None,
                "product_model": model if source else "", "rights_status": source.get("rights_status", "unconfirmed") if source else "owned",
                "visual_check_status": "needs_review", "is_generated": False, "generation_prompt": None,
                "render_method": "deterministic_svg", "width": width, "height": height,
                "text_content": ["HUAWEI PC / NOTES", f"0{index+1}", title, model[:50],
                    request['strategy']['audience'][:36] + " · " + ['主题封面','场景清单','选购参考'][index],
                    caption, *extra_text],
                "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest() if source else None,
                "task_id": request["task_id"], "strategy_id": request["strategy"]["strategy_id"], "created_at": now()}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class FactCheckAdapter:
    """A owns all semantic factual checking; B only validates the response contract."""
    def check(self, payload):
        if payload.get("a_binding") is not None:
            from .a_bridge import check_final
            return self.validate(check_final(payload), payload)
        endpoint = os.environ.get("FACT_CHECK_FINAL_URL", "")
        if not endpoint:
            return {"status": "pending", "claims": [], "reason": "A 的最终事实核查接口尚未配置。"}
        parsed = urlsplit(endpoint)
        if parsed.username or parsed.password or parsed.fragment or parsed.query or not (parsed.scheme == "https" or (parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "::1"))):
            raise ContentError("FACT_CHECK_CONFIG", "核查地址须使用 HTTPS，或本机 HTTP。", 503)
        headers = {"Content-Type": "application/json"}
        token = os.environ.get("FACT_CHECK_API_KEY")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            req = Request(endpoint, data=json.dumps(payload, ensure_ascii=False).encode(), headers=headers, method="POST")
            with build_opener(NoRedirect()).open(req, timeout=30) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise ValueError()
            result = json.loads(raw)
            if result.get("success") is not True or not isinstance(result.get("data"), dict):
                raise ValueError()
            return self.validate(result["data"], payload)
        except ContentError:
            raise
        except Exception:
            raise ContentError("FACT_CHECK_UNAVAILABLE", "A 的核查服务未完成请求，成果已保留，仍不可直接发布。", 503) from None

    @staticmethod
    def validate(result, payload):
        if result.get("status") not in ("passed", "blocked", "pending") or result.get("content_hash") != payload["content_hash"]:
            raise ContentError("FACT_CHECK_CONTRACT", "核查响应须包含当前 content_hash 和合法状态。", 502)
        claims = result.get("claims")
        if not isinstance(claims, list):
            raise ContentError("FACT_CHECK_CONTRACT", "核查响应缺少 claims 数组。", 502)
        for c in claims:
            if not isinstance(c, dict) or c.get("status") not in ("supported", "unsupported", "conflicting", "needs_confirmation", "not_applicable"):
                raise ContentError("FACT_CHECK_CONTRACT", "核查条目状态不合法。", 502)
            if c["status"] == "supported" and not c.get("source_refs"):
                raise ContentError("FACT_CHECK_CONTRACT", "已支持的事实缺少来源引用。", 502)
        if any(c["status"] in ("unsupported", "conflicting", "needs_confirmation") for c in claims):
            result = {**result, "status": "blocked"}
        if result["status"] == "passed" and result.get("coverage") != "complete":
            result = {**result, "status": "pending", "reason": "核查未声明覆盖全部最终文案。"}
        return result
