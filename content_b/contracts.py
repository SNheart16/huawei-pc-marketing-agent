"""Versioned boundary between A's confirmed strategy and B's deliverable."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re


class ContentError(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def text(value, field, limit=4000, required=False):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise ContentError("INVALID_INPUT", f"{field} 必须为{'非空' if required else ''}文本，最多 {limit} 字。")
    return value.strip()


def normalize(payload):
    if not isinstance(payload, dict):
        raise ContentError("INVALID_INPUT", "请求必须是 JSON 对象。")
    request = deepcopy(payload)
    s = request.get("strategy")
    if not isinstance(s, dict):
        raise ContentError("STRATEGY_REQUIRED", "请传递完整的已确认策略。")
    if request.get("confirmed") is not True:
        raise ContentError("CONFIRM_STRATEGY", "策略须由用户确认后再生成。")
    request["task_id"] = text(request.get("task_id", ""), "task_id", 128, True)
    s["strategy_id"] = text(s.get("strategy_id", ""), "strategy_id", 128, True)
    for key in ("topic", "audience", "audience_need", "core_message"):
        s[key] = text(s.get(key, ""), key, 2000, True)
    for key in ("content_angle", "content_format", "cta", "tone", "constraints"):
        s[key] = text(s.get(key, ""), key)
    for key in ("content_outline", "avoid", "pending_confirmations", "risk_notes", "assumptions"):
        values = s.get(key, [])
        if not isinstance(values, list) or len(values) > 30:
            raise ContentError("INVALID_INPUT", f"{key} 应为最多 30 项的数组。")
        s[key] = [text(v, key, 2000) for v in values]
    request["platform"] = text(request.get("platform", ""), "platform", 50, True)
    limits = {"小红书": (20, 900), "公众号": (64, 6000), "微信公众号": (64, 6000), "微信朋友圈": (40, 500), "门店朋友圈": (40, 500), "门店海报": (24, 300), "通用草稿": (64, 2000)}
    if request["platform"] not in limits:
        raise ContentError("UNSUPPORTED_PLATFORM", "B 当前支持小红书、公众号、朋友圈、海报及通用图文。")
    request["limits"] = dict(zip(("title", "body"), limits[request["platform"]]))
    product = request.get("product_context", {})
    if not isinstance(product, dict):
        raise ContentError("INVALID_INPUT", "product_context 必须为对象。")
    product["model"] = text(product.get("model", ""), "product.model", 200)
    facts = product.get("facts", [])
    if not isinstance(facts, list) or len(facts) > 50:
        raise ContentError("INVALID_INPUT", "facts 必须为最多 50 项的数组。")
    accepted, excluded = [], []
    for i, fact in enumerate(facts):
        if not isinstance(fact, dict):
            raise ContentError("INVALID_INPUT", "每项事实须为包含 claim、status、source_ref 的对象。")
        f = {k: text(fact.get(k, ""), f"fact.{k}", 2000) for k in ("claim", "source_ref", "status", "product_model", "valid_until")}
        # Preserve evidence and limitations without granting extra eligibility.
        for key in ("evidence_text", "source_type", "retrieved_at"):
            if key in fact:
                f[key] = text(fact[key], f"fact.{key}", 4000)
        f["fact_id"] = text(fact.get("fact_id", f"fact-{i}"), "fact_id", 128, True)
        expired = False
        if f["valid_until"]:
            try:
                expiry = datetime.fromisoformat(f["valid_until"].replace("Z", "+00:00"))
                expired = expiry.tzinfo is None or expiry <= datetime.now(timezone.utc)
            except ValueError:
                expired = True
        if (f["status"] in ("supported", "verified") and f["source_ref"] and f["claim"]
                and product["model"] and f["product_model"] == product["model"] and not expired):
            accepted.append(f)
        else:
            excluded.append(f)
    if len({f["fact_id"] for f in accepted}) != len(accepted):
        raise ContentError("INVALID_INPUT", "fact_id 不能重复。")
    product["facts"] = accepted
    request["product_context"] = product
    request["excluded_facts"] = excluded
    request["copy_mode"] = request.get("copy_mode", "assembly")
    if request["copy_mode"] not in ("assembly", "llm"):
        raise ContentError("INVALID_INPUT", "copy_mode 应为 assembly 或 llm。")
    request["image_mode"] = request.get("image_mode", "pregenerated")
    if request["image_mode"] not in ("pregenerated", "layout", "ai_reference"):
        raise ContentError("INVALID_INPUT", "image_mode 应为 pregenerated 或 layout。")
    request['reference_id'] = text(request.get('reference_id', ''), 'reference_id', 128)
    count = request.get("image_count", 1)
    if type(count) is not int or not 1 <= count <= 4:
        raise ContentError("INVALID_INPUT", "image_count 为 1 到 4。")
    if request["image_mode"] == "layout" and count > 3:
        raise ContentError("INVALID_INPUT", "旧版排版模式最多支持 3 张图片。")
    request["image_count"] = count
    request["art_direction"] = request.get("art_direction", "editorial")
    if request["art_direction"] not in ("editorial", "warm", "minimal"):
        raise ContentError("INVALID_INPUT", "未知视觉方向。")
    return request


def validate_copy(copy, request):
    if not isinstance(copy, dict):
        raise ContentError("BAD_MODEL_OUTPUT", "文案服务未返回结构化成果。", 502)
    result = {k: text(copy.get(k, ""), k, request["limits"].get(k, 1000), k in ("title", "body")) for k in ("title", "body", "cta")}
    tags = copy.get("hashtags", [])
    if not isinstance(tags, list) or len(tags) > 8:
        raise ContentError("BAD_MODEL_OUTPUT", "标签最多 8 个。", 502)
    result["hashtags"] = [text(t, "hashtag", 40) for t in tags]
    if not request["strategy"]["cta"] and result["cta"]:
        raise ContentError("QUALITY_FAILED", "策略未要求行动引导，生成结果却添加了 CTA。", 422)
    return result


def local_warnings(copy, request):
    """Delivery lint only. Never presented as A's factual verification."""
    value = "\n".join([copy["title"], copy["body"], copy["cta"], *copy["hashtags"]])
    warnings = []
    for word in ["全网最低", "百分之百", "保证流畅", "绝不卡顿", "买到就是赚到", "闭眼入", "最强", *request["strategy"]["avoid"]]:
        if word and word in value:
            warnings.append(f"需修改表达：{word}")
    evidence = " ".join(f["claim"] for f in request["product_context"]["facts"])
    # Remove the known model name before checking numerical claims.
    claims = value.replace(request["product_context"]["model"], "") if request["product_context"]["model"] else value
    for token in re.findall(r"\d+(?:\.\d+)?\s*(?:小时|英寸|元|GB|TB|kg|GHz|Hz|%|克)", claims, re.I):
        if token not in evidence:
            warnings.append(f"缺少来源支持的数值：{token}")
    if not request["strategy"]["cta"] and re.search(r"立即购买|立即下单|欢迎到店|赶紧抢购", value):
        warnings.append("正文出现策略未要求的销售行动引导。")
    return list(dict.fromkeys(warnings))
