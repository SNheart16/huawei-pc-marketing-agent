"""Adapt read-only knowledge documents into provenance-bound FactRecords.

This adapter deliberately does not call an LLM or promote retrieved claims to
verified facts. It only extracts literal statements from factual sections in
documents already returned by KnowledgeService.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timezone
from pathlib import PurePosixPath
from typing import Any, Dict, Iterable, Optional, Tuple
from urllib.parse import urlsplit

from .ima_client import ImaClientError
from .knowledge_service import DEFAULT_KB_NAME, KnowledgeService
from .v2_contracts import validate_fact_record


_FACT_HEADING = re.compile(
    r"已确认事实|确定事实|确认事实|支撑事实|官方规格摘录|产品参数事实|"
    r"操作系统|尺寸与重量|屏幕|处理器|存储|显卡|内存|无线连接|电池|接口|"
    r"键盘|触控板|摄像头|音频|特色应用|包装清单|适用范围|适用条件|使用条件|限定条件|限制与条件"
)
_NON_FACT_HEADING = re.compile(
    r"来源|价格|报价|库存|优惠|折扣|促销|活动|限制|待核验|"
    r"用户追问|合规|案例|建议|图片使用|图片规则|营销|风险|总结|附录"
)
_DYNAMIC_CLAIM = re.compile(
    r"价格|售价|库存|优惠|折扣|促销|赠品|补贴|优惠券|报价|当日|现货|有货|发货|"
    r"服务费用|服务承诺|售后承诺|保修承诺|上门服务|维修承诺|交期|销量|排名|限时|满减|券后|到手价",
    re.I,
)
_NON_PRODUCT_DOCUMENT = re.compile(
    r"价格|报价|库存|优惠|促销|活动|案例|传播|海报|素材库|图片索引|卖点与限制|演示|demo|prototype",
    re.I,
)
_EDITORIAL_RULE = re.compile(
    r"目录名.{0,30}(?:不能|不可|不得)|(?:不能|不可|不得).{0,30}(?:扩展|推断|混用)|"
    r"仅用于检索|仅作检索|(?:不要将|不得将).{0,30}(?:作为事实|参数|宣传|证据)|核验规则|资料规则|"
    r"(?:系统|CPU|内存|SSD).{0,30}(?:需要按|必须按).{0,20}(?:SKU|销售)",
    re.I,
)
_ABSOLUTE_WINDOWS = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")
_EXPLICIT_EXPIRY = re.compile(r"(?:有效期至|有效至|valid[_ ]until)\s*[:：]?\s*(\d{4}-\d{2}-\d{2})", re.I)
_CONDITION_HEADING = re.compile(r"适用范围|适用条件|使用条件|限定条件|限制与条件")


class ResearchResult(dict):
    """Public retrieval data plus a process-only original-document snapshot.

    The attribute is intentionally not a JSON field: HTTP responses never
    serialize these bodies. The task repository keeps it only in memory.
    """

    def __init__(self, value: dict, evidence_documents: Optional[list] = None) -> None:
        super().__init__(value)
        self.evidence_documents = evidence_documents or []


class ProductResearchService:
    """Retrieve one product from a single configured source and map its facts."""

    def __init__(self, knowledge_service: Any = None) -> None:
        self.knowledge_service = knowledge_service or KnowledgeService()

    def retrieve_product_facts(
        self,
        product_query: str,
        kb_name: str = DEFAULT_KB_NAME,
    ) -> dict:
        if not isinstance(product_query, str) or not product_query.strip():
            return self._empty(
                "needs_input", product_query, kb_name, "请先提供产品或型号。", "PRODUCT_REQUIRED",
                mode=self._configured_mode(), source_status="ok",
            )
        if not isinstance(kb_name, str) or not kb_name.strip():
            return self._empty(
                "error", product_query, kb_name, "知识库名称配置无效。", "INVALID_KB_NAME",
                mode=self._configured_mode(), source_status="ok",
            )

        query = product_query.strip()
        try:
            retrieved = self.knowledge_service.retrieve_product_documents(query, kb_name)
        except ImaClientError as exc:
            kind = exc.kind or "unavailable"
            quota_limited = kind == "quota_limited" or exc.code == 220021
            code = "KNOWLEDGE_QUOTA_LIMITED" if quota_limited else "KNOWLEDGE_SOURCE_UNAVAILABLE"
            message = "ima 资料读取额度已达上限。" if quota_limited else "知识来源暂时不可用或请求超时。"
            status = "quota_limited" if quota_limited else "unavailable"
            mode = "local" if getattr(self.knowledge_service, "mode", "ima") == "local" else "ima"
            return self._empty("error", query, kb_name, message, code, mode=mode, source_status=status)
        except Exception:
            mode = "local" if getattr(self.knowledge_service, "mode", "ima") == "local" else "ima"
            return self._empty(
                "error", query, kb_name, "知识来源读取失败；未保存本次检索结果。",
                "KNOWLEDGE_SOURCE_ERROR", mode=mode, source_status="unavailable",
            )

        if not isinstance(retrieved, dict):
            return self._empty("error", query, kb_name, "知识来源返回格式无效。", "INVALID_KNOWLEDGE_RESPONSE")
        knowledge_source = self._source_info(retrieved.get("knowledge_source"), kb_name)
        client_status = retrieved.get("status")
        candidates = self._safe_candidates(retrieved.get("candidate_models"))
        selected = retrieved.get("selected_product_model")
        local_fallback_available = (
            knowledge_source["mode"] == "local"
            and client_status in {"success", "partial"}
            and bool(retrieved.get("documents"))
        )
        if knowledge_source["status"] == "quota_limited" and knowledge_source["mode"] == "ima":
            return self._result(
                "error", query, None, candidates, [], [], knowledge_source,
                retrieved.get("warnings"), retrieved.get("missing_information"),
                {"code": "KNOWLEDGE_QUOTA_LIMITED", "message": "ima 资料读取额度已达上限。"},
            )
        if knowledge_source["status"] == "unavailable" and not local_fallback_available:
            return self._result(
                "error", query, None, candidates, [], [], knowledge_source,
                retrieved.get("warnings"), retrieved.get("missing_information"),
                {"code": "KNOWLEDGE_SOURCE_UNAVAILABLE", "message": knowledge_source["message"]},
            )
        if client_status == "error":
            return self._result(
                "error", query, None, candidates, [], [], knowledge_source,
                retrieved.get("warnings"), retrieved.get("missing_information"),
                {"code": "KNOWLEDGE_SOURCE_ERROR", "message": "知识来源未完成检索；未保存事实。"},
            )
        if client_status == "conflict" or len(candidates) > 1:
            return self._result(
                "conflict", query, None, candidates, [], [], knowledge_source,
                retrieved.get("warnings"), self._append(retrieved.get("missing_information"), "请确认唯一的精确产品型号。"),
            )
        if not self._same_model(query, selected):
            no_documents = not retrieved.get("documents")
            status = "needs_input" if client_status == "needs_input" or no_documents else "conflict"
            message = "未取得该精确型号的资料。" if no_documents else "检索结果未能与用户指定的精确型号一致。"
            missing = self._append(retrieved.get("missing_information"), message)
            return self._result(
                status, query, None, candidates, [], [], knowledge_source,
                retrieved.get("warnings"), missing,
            )
        documents, fact_records, warnings, evidence_documents = self._adapt_documents(
            retrieved.get("documents"), query, knowledge_source["mode"],
        )
        warnings = self._append(warnings, retrieved.get("warnings"))
        missing = self._append(retrieved.get("missing_information"))
        conflicts = self._explicit_conflicts(fact_records)
        if conflicts:
            return self._result(
                "conflict", query, None, candidates, [], documents, knowledge_source,
                self._append(warnings, "同一精确型号的资料出现不一致的明确参数；未保存任一冲突事实。"),
                self._append(missing, conflicts),
                {"code": "SOURCE_CONFLICT", "message": "资料参数存在冲突，请核对来源与配置条件。"},
            )
        if not retrieved.get("documents"):
            status = "needs_input"
            missing = self._append(missing, "未找到该精确型号的可读资料。")
        elif not fact_records:
            status = "partial"
            missing = self._append(missing, "命中文档中没有可安全转换的稳定产品事实片段。")
        elif client_status in {"partial", "needs_input"}:
            status = "partial"
        elif client_status == "success":
            status = "success"
        else:
            status = "partial"

        if any(record["status"] == "stale" for record in fact_records):
            status = "partial"
            warnings = self._append(warnings, "部分事实已超过资料明确标注的有效期，不应作为当前事实使用。")
            missing = self._append(missing, "存在已过期资料事实；使用前需重新检索并确认。")
        if any(record["valid_until"] is None for record in fact_records):
            warnings = self._append(warnings, "部分资料未声明明确有效期；retrieved_at 仅是本次检索时间，资料当前有效性未知。")
            missing = self._append(missing, "部分资料未明确有效期，当前有效性仍需确认。")
        return self._result(
            status, query, selected, candidates, fact_records, documents, knowledge_source,
            warnings, missing, evidence_documents=evidence_documents,
        )

    def _adapt_documents(self, raw_documents: Any, product_model: str, mode: str) -> Tuple[list, list, list, list]:
        if not isinstance(raw_documents, list):
            return [], [], ["知识来源未返回资料列表。"], []
        documents = []
        evidence_documents = []
        facts = []
        warnings = []
        seen_claims = set()
        retrieved_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        for document in raw_documents:
            if not isinstance(document, dict) or not self._same_model(product_model, document.get("product_model")):
                if isinstance(document, dict) and document.get("product_model"):
                    warnings = self._append(warnings, "已排除与目标精确型号不一致的资料，未混合型号事实。")
                continue
            title = document.get("document_title")
            content = document.get("content")
            if not isinstance(title, str) or not isinstance(content, str) or not content.strip():
                continue
            reference = self._source_ref(document, mode)
            if not reference:
                warnings = self._append(warnings, f"《{title}》缺少安全、可追溯的来源引用，已排除。")
                continue
            if _NON_PRODUCT_DOCUMENT.search(f"{title} {reference}"):
                warnings = self._append(warnings, f"《{title}》属于动态销售或营销素材资料，未转换为稳定产品事实。")
                if re.search(r"活动|促销|优惠|价格|库存", f"{title} {reference}"):
                    expiry = self._valid_until(content)
                    if expiry and expiry < datetime.now(timezone.utc):
                        warnings = self._append(warnings, f"《{title}》已超过明确有效期，不可作为当前活动依据。")
                    elif not expiry:
                        warnings = self._append(warnings, f"《{title}》未标明有效期，活动或价格有效性未知。")
                continue

            valid_until = self._valid_until(content)
            document_fact_ids = []
            for claim, evidence_text in self._factual_snippets(content):
                if _DYNAMIC_CLAIM.search(claim):
                    warnings = self._append(warnings, f"《{title}》包含动态销售或服务信息，未转换为稳定产品事实。")
                    continue
                if _EDITORIAL_RULE.search(claim):
                    warnings = self._append(warnings, f"《{title}》中的检索或核验规则未作为产品事实保存。")
                    continue
                if len(claim) > 8000 or len(evidence_text) > 8000:
                    warnings = self._append(warnings, f"《{title}》事实区块过长，未截断或丢失其适用条件；请拆分资料。")
                    continue
                if len(facts) >= 500:
                    warnings = self._append(warnings, "本次达到 500 条事实记录上限；未截断单条证据。")
                    break
                key = re.sub(r"[\W_]+", "", claim.casefold())
                identity = (reference, key)
                if not key or identity in seen_claims:
                    continue

                seen_claims.add(identity)
                fact_id = "fact-" + hashlib.sha256(f"{product_model}\0{reference}\0{key}".encode("utf-8")).hexdigest()[:20]
                status = "stale" if valid_until and valid_until < datetime.now(timezone.utc) else "retrieved"
                record = {
                    "fact_id": fact_id,
                    "product_model": product_model,
                    "claim": claim,
                    "evidence_text": evidence_text,
                    "source_ref": reference,
                    "source_type": self._source_type(document, content),
                    "retrieved_at": retrieved_at,
                    "valid_until": valid_until.isoformat(timespec="seconds").replace("+00:00", "Z") if valid_until else None,
                    "status": status,
                }
                facts.append(validate_fact_record(record))
                document_fact_ids.append(fact_id)
            if document_fact_ids:
                evidence_documents.append({
                    "source_ref": reference,
                    "product_model": product_model,
                    "content": content,
                })
                documents.append({
                    "document_title": title,
                    "source_ref": reference,
                    "fact_ids": document_fact_ids,
                })
        return documents, facts, warnings, evidence_documents

    @staticmethod
    def _factual_snippets(content: str) -> Iterable[Tuple[str, str]]:
        # Slice original text, including blank lines. Never rewrite the evidence.
        # An immediately following qualification section belongs to the claim too.
        headings = list(re.finditer(r"^#{1,6}[^\S\r\n]+([^\r\n]+)", content, re.M))
        for index, heading in enumerate(headings):
            name = heading.group(1).strip(" *`_")
            is_condition = bool(_CONDITION_HEADING.search(name))
            if not _FACT_HEADING.search(name) or (_NON_FACT_HEADING.search(name) and not is_condition):
                continue
            end = headings[index + 1].start() if index + 1 < len(headings) else len(content)
            if not content[heading.end():end].strip():
                continue
            if not is_condition and index + 1 < len(headings):
                following = headings[index + 1]
                if _CONDITION_HEADING.search(following.group(1)):
                    end = headings[index + 2].start() if index + 2 < len(headings) else len(content)
            text = content[heading.end():end].strip()
            yield name + "：\n" + text, content[heading.start():end].strip()

    @staticmethod
    def _explicit_conflicts(records: list) -> list:
        """Only compare explicit unqualified key/value parameters; prose and
        configuration choices still require a later fact-checking stage."""
        values = {}
        for record in records:
            # Differing configuration-specific statements are not automatically
            # contradictions. Leave semantic checking to the explicit checker.
            if re.search(r"仅|适用|SKU|Windows|HarmonyOS|不同配置|可选", record["evidence_text"], re.I):
                continue
            for line in record["evidence_text"].splitlines():
                match = re.match(r"^\s*[-*+]?\s*(屏幕尺寸|重量|电池容量|分辨率)\s*[:：]\s*(.+?)\s*$", line)
                if not match:
                    continue
                value = match.group(2)
                if re.search(r"或|可选|版本|配置|仅|条件|约|最高|最低", value):
                    continue
                key = match.group(1)
                compact = re.sub(r"\s+", "", value).rstrip("。.")
                values.setdefault(key, set()).add(compact)
        return [f"资料中的{key}不一致，需要核对原文及配置。" for key, items in values.items() if len(items) > 1]

    @staticmethod
    def _same_model(left: Any, right: Any) -> bool:
        if not isinstance(left, str) or not isinstance(right, str) or not left.strip() or not right.strip():
            return False
        normalize = lambda value: re.sub(r"[\W_]+", "", re.sub(r"^HUAWEI\s*", "", value.strip(), flags=re.I).casefold())
        return normalize(left) == normalize(right)

    @staticmethod
    def _source_ref(document: dict, mode: str) -> Optional[str]:
        if mode == "local":
            reference = document.get("source_ref") or document.get("source")
            if not isinstance(reference, str) or not reference.strip():
                return None
            normalized = reference.replace("\\", "/").strip()
            path = PurePosixPath(normalized)
            if _ABSOLUTE_WINDOWS.match(reference) or path.is_absolute() or ".." in path.parts:
                return None
            return path.as_posix()
        media_id = document.get("media_id")
        if isinstance(media_id, str) and media_id.strip():
            return "ima_media_id:" + media_id.strip()
        source = document.get("source")
        if isinstance(source, str):
            try:
                parsed = urlsplit(source)
            except ValueError:
                return None
            if parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password:
                return source
        return None

    @staticmethod
    def _source_type(document: dict, content: str) -> str:
        declared = document.get("source_type")
        if declared in {"official", "trusted_third_party"}:
            return declared
        source = document.get("source")
        if isinstance(source, str):
            try:
                parsed = urlsplit(source)
            except ValueError:
                parsed = None
            if parsed and parsed.scheme == "https" and parsed.hostname:
                if parsed.hostname.casefold() == "consumer.huawei.com":
                    return "official"
                if parsed.hostname.casefold() in {"intel.com", "www.intel.com", "microsoft.com", "www.microsoft.com", "amd.com", "www.amd.com"}:
                    return "trusted_third_party"
        return "other"

    @staticmethod
    def _valid_until(content: str) -> Optional[datetime]:
        match = _EXPLICIT_EXPIRY.search(content)
        if not match:
            return None
        try:
            return datetime.combine(date.fromisoformat(match.group(1)), datetime.max.time(), tzinfo=timezone.utc)
        except ValueError:
            return None

    @staticmethod
    def _safe_candidates(value: Any) -> list:
        if not isinstance(value, list):
            return []
        candidates = []
        for candidate in value:
            if not isinstance(candidate, dict):
                continue
            item = {"product_model": candidate.get("product_model"), "sources": []}
            for source in candidate.get("sources", []):
                if isinstance(source, dict):
                    item["sources"].append({
                        key: source.get(key) for key in ("document_title", "source_ref", "media_id")
                        if isinstance(source.get(key), str)
                    })
            candidates.append(item)
        return candidates

    def _empty(
        self, status: str, query: Any, kb_name: Any, message: str, code: Optional[str] = None,
        *, mode: str = "ima", source_status: str = "unavailable",
    ) -> dict:
        knowledge_source = {
            "mode": mode, "name": kb_name if isinstance(kb_name, str) else DEFAULT_KB_NAME,
            "live": False, "status": source_status, "message": message,
        }
        return self._result(status, query, None, [], [], [], knowledge_source, [], [message],
                            {"code": code, "message": message} if code else None)

    def _configured_mode(self) -> str:
        mode = getattr(self.knowledge_service, "mode", "ima")
        return mode if mode in {"ima", "local"} else "ima"

    @staticmethod
    def _source_info(value: Any, kb_name: str) -> dict:
        if not isinstance(value, dict):
            return {"mode": "ima", "name": kb_name, "live": False, "status": "unavailable",
                    "message": "知识来源未提供来源状态。"}
        mode = value.get("mode") if value.get("mode") in {"ima", "local"} else "ima"
        status = value.get("status") if value.get("status") in {"ok", "quota_limited", "unavailable"} else "unavailable"
        message = value.get("message") if isinstance(value.get("message"), str) else "知识来源状态未知。"
        return {"mode": mode, "name": kb_name, "live": mode == "ima" and value.get("live") is True,
                "status": status, "message": message}

    @staticmethod
    def _append(*values: Any) -> list:
        result = []
        for value in values:
            items = value if isinstance(value, list) else [value]
            for item in items:
                if isinstance(item, str) and item.strip() and item not in result:
                    result.append(item)
        return result

    def _result(
        self, status: str, query: Any, selected: Any, candidates: list, facts: list,
        documents: list, knowledge_source: dict, warnings: Any, missing: Any,
        error: Optional[dict] = None,
        *, evidence_documents: Optional[list] = None,
    ) -> dict:
        value = {
            "status": status,
            "query": query if isinstance(query, str) else "",
            "selected_product_model": selected if isinstance(selected, str) else None,
            "candidate_models": candidates,
            "documents": documents,
            "fact_records": facts,
            "knowledge_source": knowledge_source,
            "warnings": self._append(warnings),
            "missing_information": self._append(missing),
            "next_action": "check_facts" if facts else "confirm_product_or_retry_research",
        }
        if error:
            value["error"] = error
        return ResearchResult(value, evidence_documents)


def retrieve_product_facts(
    product_query: str,
    kb_name: str = DEFAULT_KB_NAME,
    knowledge_service: Any = None,
) -> dict:
    """Convenience entry point for isolated retrieval and offline testing."""
    return ProductResearchService(knowledge_service).retrieve_product_facts(product_query, kb_name)
