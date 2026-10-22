"""Conservative, provenance-bound checks before strategy generation.

Only server-owned retrieval snapshots are evidence. A semantic model can help
with a rewrite, but cannot supply sources, change numbers or waive conditions.
No document bodies, credentials or local paths are logged or persisted here.
"""

from __future__ import annotations

import copy
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .llm_client import LLMClient, LLMClientError, model_json, safe_error_diagnostic
from .product_research_service import ProductResearchService
from .v2_contracts import CHECK_STATUSES, validate_fact_check_result


_DYNAMIC = re.compile(r"价格|售价|到手价|库存|现货|优惠|折扣|满减|赠品|补贴|促销|保修|保价|承诺|免费维修|上门服务|发货")
_SCENE_INFERENCE = re.compile(r"适合大学生|适合学生|提升学习|提高学习|学习效率|办公效率|人人适用|适合所有|保证.{0,8}(?:效率|体验)")
_PLANNING = re.compile(
    r"^(?:建议以|内容角度[：:]|推广目标[：:]|目标受众[：:]|"
    r"(?:大学生|学生|职场人士|消费者).{0,20}(?:需要|希望|关注)|"
    r"(?:开学季|校园学习|轻办公).{0,20}(?:场景|内容|推广))"
)
_UNSAFE_REF = re.compile(r"^(?:[a-zA-Z]:[\\/]|[\\/])|(?:^|/)(?:ui|demo|tests|prototype)(?:/|\.)|\.\.")
_YEAR = re.compile(r"\b20\d{2}\b")
_NUMBER = re.compile(r"\d+(?:\.\d+)?\s*(?:GHz|MHz|mAh|Wh|GB|TB|MB|kg|mm|cm|Hz|nit|nits|%|g|W|英寸|小时|分钟|克|千克|毫米|厘米|元)?", re.I)
_PARAMETER = re.compile(r"(?:^|\n)\s*(?:[-*+]\s*)?(重量|屏幕尺寸|电池容量|分辨率|内存|存储容量|处理器|CPU)\s*[:：]\s*([^\n]+)", re.I)
_QUALIFIER = re.compile(r"(?:仅[^，。；;\n）)]*|(?:适用(?:于|范围|条件)?|相比|相较|较上代|条件下|需另购)[^。；;\n）)]*)", re.I)
_NUMERIC_BINDING = re.compile(
    r"(内存|存储容量|屏幕尺寸|电池容量|重量)\s*(?:容量|为|约|[:：]|\s)*\s*"
    r"(\d+(?:\.\d+)?\s*(?:mAh|Wh|GB|TB|kg|mm|cm|g|英寸|克|千克))", re.I,
)
_POLARITY_PAIRS = (("不支持", "支持"), ("不兼容", "兼容"), ("不含", "包含"),
                   ("不能", "可以"), ("未提供", "提供"), ("不具备", "具备"))


def canonical(text: str) -> str:
    """Normalize formatting only, preserving polarity, alternatives and units."""
    text = text.casefold().replace("大约", "约")
    text = re.sub(r"[#*`®™\s：:，,。；;（）()\[\]【】]+", "", text)
    return re.sub(r"^[\-+]+", "", text)


def _numbers(text: str) -> set:
    return {re.sub(r"\s+", "", item.casefold()) for item in _NUMBER.findall(text)}


def _expired(record: dict) -> bool:
    if record.get("status") == "stale":
        return True
    until = record.get("valid_until")
    if not until:
        return False
    try:
        when = datetime.fromisoformat(until.replace("Z", "+00:00"))
        return when.replace(tzinfo=when.tzinfo or timezone.utc) < datetime.now(timezone.utc)
    except (ValueError, TypeError):
        return True


def is_expired(record: dict) -> bool:
    """Public predicate used by workflow eligibility checks."""
    return _expired(record)


def _scope(text: str) -> str:
    qualifiers = _QUALIFIER.findall(text)
    qualifiers += re.findall(r"^\s*[-*#]*\s*(?:配置|SKU|版本)\s*[:：]\s*([^\n]+)", text, re.M | re.I)
    return "|".join(sorted({canonical(value) for value in qualifiers}))


def _prompt_text() -> str:
    configured = os.environ.get("FACT_CHECK_PROMPT_PATH", "").strip()
    candidates = ([Path(configured).expanduser()] if configured else [])
    candidates.append(Path(__file__).resolve().parents[2] / "prompts" / "fact-check-system.md")
    for candidate in candidates:
        try:
            text = candidate.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError, ValueError):
            continue
        if text.strip():
            return text
    raise ValueError("Fact-check system prompt is unavailable")


class FactChecker:
    """Check one batch independently of HTTP and the task repository.

    ``research_context`` is a private, in-memory server snapshot from research,
    never a client-supplied request field. A client can be injected offline.
    """

    def __init__(self, llm_client: Any = None) -> None:
        self.llm_client = llm_client

    def check(self, task: dict, claims: list, research_context: Optional[dict] = None) -> dict:
        context = research_context or {}
        records = {item["fact_id"]: item for item in context.get("retrieved_fact_records", [])}
        current = {item["fact_id"]: item for item in task["fact_records"]}
        documents = context.get("evidence_documents", [])
        source = copy.deepcopy(context.get("knowledge_source") or {
            "mode": "unknown", "name": "unknown", "live": False,
            "status": "unavailable", "message": "当前任务没有可追溯的检索来源快照。",
        })
        warnings = ["supported 仅表示本次可用来源支持，不代表最新资料或官方认证。"]
        if source.get("live") is not True:
            warnings.append("本次来源非实时在线读取；核查不证明当前库存、价格或活动状态。")
        if any(record.get("source_type") in {"other", "unknown"} for record in records.values()):
            warnings.append("部分来源可靠性尚未独立确认，保留原来源类别，不升级为官方认证。")
        if any(record.get("valid_until") is None for record in records.values()):
            warnings.append("资料未声明有效期时，当前有效性未知；retrieved_at 仅是检索时间。")
        conflicts = self._conflicts(records, documents, task["product_query"])
        results = []
        pending = []
        for index, item in enumerate(claims):
            refs = item["fact_references"]
            selected = [records[ref] for ref in refs if ref in records]
            status, reason = self._preflight(task, item, current, records, documents, conflicts, source)
            related = {ref for ref in refs}
            if status == "conflicting":
                for ref in refs:
                    related.update(conflicts.get(ref, []))
            evidence_records = [records[ref] for ref in related if ref in records]
            # Invalid/unproven sources never become an apparent supporting citation.
            evidence_records = [r for r in evidence_records if self._provenance(r, documents, task["product_query"]) is None]
            result = self._result(task, item, status or "needs_confirmation", evidence_records, reason)
            results.append(result)
            if status is None:
                pending.append({"index": index, "claim": item["claim"], "records": [
                    {key: record[key] for key in ("fact_id", "product_model", "evidence_text", "source_type", "valid_until")}
                    for record in selected
                ]})

        errors = []
        diagnostic = {"model_call_count": 0, "upstream_request_count": 0,
                      "upstream_requests": [], "status": "not_needed", "elapsed_ms": 0.0}
        if pending:
            started = time.perf_counter()
            try:
                client = self.llm_client if self.llm_client is not None else LLMClient(timeout=60)
                raw = model_json(client, _prompt_text(), {"product_model": task["product_query"], "checks": pending}, diagnostic)
                semantic = self._validate_semantic(raw, pending)
            except LLMClientError as error:
                semantic = {}
                diagnostic.update(status="failed", **safe_error_diagnostic(error))
                suffix = {"connection": "CONNECTION_FAILED", "timeout": "REQUEST_TIMEOUT",
                          "upstream_http": "UPSTREAM_HTTP_ERROR", "json_parse": "JSON_INVALID",
                          "response_schema": "RESPONSE_INVALID", "configuration": "CONFIGURATION_ERROR"}.get(error.category, "CLIENT_ERROR")
                errors.append({"code": "FACT_CHECK_" + suffix, "message": "语义核查调用未完成；未将待核查陈述标为支持，请按诊断检查后重试。"})
            except (ValueError, TypeError, KeyError) as error:
                semantic = {}
                failure_type = "response_schema" if diagnostic["status"] == "ok" else "internal"
                diagnostic.update(safe_error_diagnostic(error), status="failed")
                diagnostic["failure_type"] = failure_type
                errors.append({"code": "FACT_CHECK_RESPONSE_INVALID" if failure_type == "response_schema" else "FACT_CHECK_INTERNAL_ERROR",
                               "message": "语义核查结构无效或处理失败；未采信其输出。"})
            except Exception as error:
                semantic = {}
                diagnostic.update(status="failed", **safe_error_diagnostic(error))
                errors.append({"code": "FACT_CHECK_INTERNAL_ERROR", "message": "事实核查处理异常；未采信其输出。"})
            finally:
                diagnostic["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
            for entry in pending:
                index = entry["index"]
                assessment = semantic.get(index)
                if assessment is None:
                    results[index]["reason"] = "语义辅助调用失败；保留证据并等待重试，不以模拟结果替代。"
                    continue
                status = assessment["status"]
                if status == "supported" and not self._independent_rewrite_guard(entry["claim"], entry["records"], task["product_query"]):
                    status = "needs_confirmation"
                selected = [records[ref] for ref in claims[index]["fact_references"]]
                reasons = {
                    "supported": "改写通过引用、原文对应、参数与限定条件检查，且语义辅助判断一致；仅本次来源支持。",
                    "unsupported": "陈述未忠实表达所引证据，不能作为已支持的产品事实。",
                    "conflicting": "语义比对发现资料含义或配置存在冲突，需人工核对，不能择一采信。",
                    "needs_confirmation": "现有证据不足以可靠确认改写含义，需补充依据或保留原文限定。",
                    "not_applicable": "此项属于场景或表达建议，不是可核验的产品事实。",
                }
                results[index] = self._result(task, claims[index], status, selected, reasons[status])

        for result in results:
            validate_fact_check_result(result)
        return {
            "results": results,
            "counts": {status: sum(r["status"] == status for r in results) for status in CHECK_STATUSES},
            "blocked_fact_ids": sorted({ref for refs in conflicts.values() for ref in refs}),
            "knowledge_source": source,
            "source_types": {ref: record["source_type"] for ref, record in records.items()},
            "warnings": warnings,
            "errors": errors,
            "execution_status": "partial" if errors else "completed",
            "diagnostics": diagnostic,
        }

    def _preflight(self, task, item, current, records, documents, conflicts, source):
        claim, refs = item["claim"], item["fact_references"]
        if not refs:
            if _PLANNING.search(claim):
                return "not_applicable", "这是表达或受众规划，不是产品事实；不授予事实引用资格。"
            return "unsupported", "没有引用当前任务的服务端检索记录，用户输入或自述不能充当产品证据。"
        if any(ref not in current or ref not in records for ref in refs):
            return "unsupported", "引用不属于本任务当前检索快照，不能使用外部提交的来源或通过标签。"
        selected = [records[ref] for ref in refs]
        for record in selected:
            original = current[record["fact_id"]]
            if any(original[key] != record[key] for key in record if key != "status"):
                return "unsupported", "候选事实与本次保留的检索记录不一致，请重新检索。"
            failure = self._provenance(record, documents, task["product_query"])
            if failure:
                return failure
        if any(ref in conflicts for ref in refs):
            return "conflicting", "当前任务同一型号、同一配置的来源存在明确参数冲突；相关卖点暂停采用。"
        if _PLANNING.search(claim):
            return "not_applicable", "这是用户需求、场景或表达规划，不是已核验的产品事实。"
        text = "\n".join(record["evidence_text"] for record in selected)
        # Research attaches each immediately following condition section to
        # its own excerpt. Unrelated conditions elsewhere in the document
        # must not contaminate an independent fact (e.g. colour vs CPU SKU).
        context_text = text
        if _YEAR.findall(claim) and set(_YEAR.findall(claim)) - set(_YEAR.findall(text + task["product_query"])):
            return "conflicting", "陈述包含未属于本次精确型号的年份或版本，禁止混用其他型号资料。"
        if re.search(r"MateBook\s+X\s+Pro\s+20\d{2}", claim, re.I) and not re.search(r"MateBook\s+X\s+Pro\s+20\d{2}", task["product_query"], re.I):
            return "conflicting", "陈述指定了不同年份的 MateBook X Pro，不能借用当前型号的证据。"
        if any(_expired(record) for record in selected):
            return "needs_confirmation", "所引记录已过期或失效；不能将其作为当前有效事实，需重新取得依据。"
        if _DYNAMIC.search(claim) and not _DYNAMIC.search(text):
            return "unsupported", "所引产品证据不包含此价格、优惠、库存或服务承诺，禁止补充无依据的商业信息。"
        if _DYNAMIC.search(claim) and (source.get("live") is not True or any(not r["valid_until"] for r in selected)
                                     or not re.search(r"适用|范围|门店|地区|期间|截至|有效期", text)):
            return "needs_confirmation", "价格、库存、优惠或服务承诺缺少可确认的当前适用范围与有效依据，不能作为稳定参数。"
        if _SCENE_INFERENCE.search(claim):
            return "not_applicable", "该陈述是场景效果推断，不能由产品参数或用户需求升级为产品事实。"
        extra_numbers = _numbers(claim) - _numbers(text + task["product_query"])
        if extra_numbers:
            return "unsupported", "陈述改变或新增了证据中的数字、单位或配置参数；请恢复原文值。"
        missing_numbers = _numbers(text) - _numbers(claim)
        if missing_numbers:
            return "unsupported", "陈述省略了本条证据中的数字或单位，不能确认其参数范围；请恢复完整数值。"
        for negative, positive in _POLARITY_PAIRS:
            if negative in text and positive in claim and negative not in claim:
                return "unsupported", "陈述反转了来源中的否定或支持状态。"
            if positive in text and negative in claim and negative not in text:
                return "unsupported", "陈述反转了来源中的否定或支持状态。"
        evidence_bindings = {(label, canonical(value)) for label, value in _NUMERIC_BINDING.findall(text)}
        for label, value in _NUMERIC_BINDING.findall(claim):
            if any(key == label for key, _ in evidence_bindings) and (label, canonical(value)) not in evidence_bindings:
                return "unsupported", "数字虽在资料中出现，但其对应参数被替换；请恢复原文中的参数对应关系。"
        for term in ("Windows", "HarmonyOS", "仅", "最高", "最低", "至多", "至少", "约", "可选", "需另购", "不支持", "相比", "较上代", "相较", "条件下", "视配置"):
            if term.casefold() in context_text.casefold() and term.casefold() not in claim.casefold():
                return "unsupported", "陈述省略了来源中的配置、版本或适用限定；请补回限定条件。"
        if re.search(r"或|/|不同配置", text) and _numbers(text) - _numbers(claim):
            return "needs_confirmation", "来源包含多配置或可选参数，当前陈述未保留完整选项或未确定适用配置。"
        for term in ("更快", "领先", "优于", "第一", "官方认证", "不限", "永久", "不支持"):
            if term in claim and term not in text:
                return "unsupported", "陈述增加了证据未表达的比较、认证、绝对承诺或否定含义。"
        if canonical(claim) != canonical(text) and any(
            canonical(qualifier) not in canonical(claim) for qualifier in _QUALIFIER.findall(text)
        ):
            return "needs_confirmation", "改写未完整保留原文的适用范围或比较条件，需恢复限定或逐项确认。"
        # Exact original candidates are checked against the actual raw snapshot,
        # not their retrieved/supported label and not a model's confidence.
        if len(selected) == 1 and canonical(claim) == canonical(selected[0]["evidence_text"]):
            return "supported", "陈述与本次取得的原文一致，型号、参数和限定条件完整；仅本次可用来源支持。"
        if any(canonical(claim) == canonical(r["evidence_text"]) for r in selected) and len(selected) > 1:
            return "needs_confirmation", "包含多条引用，需逐项明确各自支持的内容，不能用单个片段替代全部核查。"
        return None, "需要辅助比对改写含义，尚未判定支持。"

    @staticmethod
    def _provenance(record, documents, model):
        if not ProductResearchService._same_model(record.get("product_model"), model):
            return "conflicting", "引用事实不属于当前精确型号或版本。"
        ref = record.get("source_ref", "")
        if not ref or _UNSAFE_REF.search(ref):
            return "unsupported", "来源缺失、不可追溯或属于演示/用户输入内容，不可作为产品证据。"
        matches = [doc for doc in documents if doc.get("source_ref") == ref
                   and ProductResearchService._same_model(doc.get("product_model"), model)]
        if not matches:
            return "needs_confirmation", "缺少本次原资料快照，无法核对 evidence_text 与原资料的对应关系，请重新检索。"
        if not record.get("evidence_text") or not any(record["evidence_text"] in doc.get("content", "") for doc in matches):
            return "unsupported", "evidence_text 无法逐字对应本次取得的原资料，不能采信。"
        return None

    def _conflicts(self, records, documents, model):
        groups = {}
        for record in records.values():
            if self._provenance(record, documents, model) is not None or _expired(record):
                continue
            text = record["evidence_text"]
            parameters = _PARAMETER.findall(text)
            named = {parameter.casefold() for parameter, _ in parameters}
            parameters += [(key, value) for key, value in _NUMERIC_BINDING.findall(text)
                           if key.casefold() not in named]
            for parameter, value in parameters:
                # Explicit choices/approximations need a human/semantic review,
                # rather than inventing a contradiction between configurations.
                if re.search(r"或|/|可选|约|最高|最低", value):
                    continue
                groups.setdefault((parameter.casefold(), _scope(text)), []).append((record["fact_id"], canonical(value)))
            for verb, feature in re.findall(r"(不支持|支持|不兼容|兼容)([^。；;\n]+)", text):
                groups.setdefault((verb.removeprefix("不"), canonical(feature), _scope(text)), []).append(
                    (record["fact_id"], "negative" if verb.startswith("不") else "positive")
                )
        conflicts = {}
        for group in groups.values():
            if len({value for _, value in group}) > 1:
                ids = {ref for ref, _ in group}
                for ref in ids:
                    conflicts.setdefault(ref, set()).update(ids)
        return conflicts

    @staticmethod
    def _independent_rewrite_guard(claim, records, model):
        # The model alone is not an evidence oracle. Require every material
        # word/bigram to occur in the referenced text after removing only
        # non-material framing words. Unknown paraphrases stay unconfirmed.
        evidence = canonical("\n".join(r["evidence_text"] for r in records))
        residue = claim.replace(model, "")
        for word in ("这款电脑", "这款产品", "该产品", "本机", "搭载", "配备", "采用", "拥有", "提供", "其中", "以及", "和", "的", "为", "是", "个"):
            residue = residue.replace(word, "")
        residue = canonical(residue)
        tokens = re.findall(r"[a-z]+|\d+(?:\.\d+)?|[\u4e00-\u9fff]+", residue)
        for token in tokens:
            if re.fullmatch(r"[\u4e00-\u9fff]+", token):
                chunks = [token[i:i + 2] for i in range(max(1, len(token) - 1))]
                if any(chunk not in evidence for chunk in chunks):
                    return False
            elif token not in evidence:
                return False
        return bool(tokens)

    @staticmethod
    def _validate_semantic(value, pending):
        if not isinstance(value, dict) or set(value) != {"checks"} or not isinstance(value["checks"], list):
            raise ValueError("Invalid semantic response")
        expected = {entry["index"]: entry for entry in pending}
        checked = {}
        for item in value["checks"]:
            if not isinstance(item, dict) or set(item) != {"index", "status", "evidence"}:
                raise ValueError("Invalid semantic item")
            index = item["index"]
            if isinstance(index, bool) or not isinstance(index, int) or index not in expected or index in checked:
                raise ValueError("Invalid semantic index")
            if item["status"] not in CHECK_STATUSES or not isinstance(item["evidence"], list):
                raise ValueError("Invalid semantic assessment")
            originals = {r["fact_id"]: r["evidence_text"] for r in expected[index]["records"]}
            cited = set()
            for quote in item["evidence"]:
                if (not isinstance(quote, dict) or set(quote) != {"fact_id", "quote"}
                        or quote["fact_id"] not in originals or not isinstance(quote["quote"], str)
                        or not quote["quote"].strip() or quote["quote"] not in originals[quote["fact_id"]]):
                    raise ValueError("Ungrounded semantic citation")
                cited.add(quote["fact_id"])
            if item["status"] == "supported" and cited != set(originals):
                raise ValueError("Missing semantic citations")
            checked[index] = item
        if set(checked) != set(expected):
            raise ValueError("Missing semantic assessments")
        return checked

    @staticmethod
    def _result(task, item, status, records, reason):
        action = {"supported": "retain", "unsupported": "rewrite", "conflicting": "confirm",
                  "needs_confirmation": "confirm", "not_applicable": "none"}[status]
        return {
            "task_id": task["task_id"], "task_revision": task["revision"],
            "claim": item["claim"], "fact_references": list(item["fact_references"]),
            "status": status,
            "evidence": list(dict.fromkeys(r["evidence_text"] for r in records)),
            "source_refs": list(dict.fromkeys(r["source_ref"] for r in records)),
            "reason": reason, "suggested_action": action,
        }
