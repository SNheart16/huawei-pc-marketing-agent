"""Evidence-bound final text checking, with explicit unknown visual coverage.

No generation or automatic editing occurs. Client claims and support labels
are not inputs to the decision. Only server-owned, strategy-adopted evidence
is sent to the independent full-text reviewer and the existing FactChecker.
"""

from __future__ import annotations

import copy
import re
import time
from pathlib import Path
from typing import Any

from .fact_checker import FactChecker, canonical
from .final_content_contracts import content_digest, content_texts, validate_final_content
from .llm_client import LLMClient, model_json, safe_error_diagnostic
from .statement_review import CLASSIFICATION_RULES, FACT_ASSERTION
from .v2_contracts import CHECK_STATUSES, validate_fact_check_result


_KINDS = {"factual", "planning", "constraint", "user_context", "assumption", "limitation", "uncertain"}
_ISSUES = {
    "user_constraint": "成稿与用户当前限制条件不一致。",
    "strategy_mismatch": "成稿实质偏离当前已确认策略，需修改或重新确认策略。",
    "exaggeration": "存在未经依据支持的夸大、绝对化或比较表达。",
    "invalid_reference": "引用不属于当前策略可用事实，不能采信客户端自行提交的来源。",
    "coverage": "独立覆盖检查发现未完整核查的事实子句，未自动通过。",
}
_ABSOLUTE = re.compile(r"行业第一|全国第一|全球第一|绝对领先|永不(?:卡顿|损坏)|保证.{0,12}(?:提升|提高|成功)|100%|零风险|完美无缺")
_CITATION = re.compile(r"\[(fact-[\w-]+|F\d+)\]")
_EXTRA_ASSERTION = re.compile(r"\d+(?:\.\d+)?\s*(?:nits?|W|g)\b|(?:售价|到手价|优惠|补贴|折扣|续航|内存|重量)\s*[:：为]?\s*\d+", re.I)


class FinalCheckError(RuntimeError):
    def __init__(self, code: str, message: str, diagnostics: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.diagnostics = code, message, diagnostics or {}


def _diagnostics(stages: list, started: float) -> dict:
    return {"elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "model_call_count": sum(item.get("model_call_count", 0) for item in stages),
            "upstream_request_count": sum(item.get("upstream_request_count", 0) for item in stages),
            "stages": copy.deepcopy(stages)}


def _blocked(path: str, claim: str, category: str, *, status="unsupported") -> dict:
    return {"field_path": path, "claim": claim, "status": status,
            "reason": _ISSUES[category], "suggested_action": "删除或忠实改写后重新核查；提示或免责声明不能替代修正。"}


def _review_request(task: dict, strategy: dict, facts: list, content: dict) -> dict:
    return {
        "task": {key: task[key] for key in ("product_query", "audience", "platform", "goal", "scene", "constraints", "excluded_scenes")},
        "confirmed_strategy": {key: strategy[key] for key in (
            "topic", "audience", "core_message", "content_angle", "content_format", "content_outline", "cta", "assumptions",
        )},
        "eligible_fact_records": [{key: record[key] for key in (
            "fact_id", "product_model", "claim", "evidence_text", "source_ref", "source_type", "valid_until",
        )} for record in facts],
        "fields": [{"field_path": path, "text": text} for path, text in content_texts(content)],
    }


def _validate_review(task: dict, content: dict, value: Any, eligible_ids: set) -> tuple:
    """Validate full-field coverage, exact extracts and references independently."""
    if (not isinstance(value, dict) or set(value) != {"fields", "fact_claims", "issues"}
            or any(not isinstance(value[key], list) for key in value)
            or len(value["fact_claims"]) > 150 or len(value["issues"]) > 150):
        raise ValueError("Invalid final review shape")
    texts = dict(content_texts(content))
    seen, expected, blockers = set(), set(), []
    for item in value["fields"]:
        if not isinstance(item, dict) or set(item) != {"field_path", "text", "kind", "claims"}:
            raise ValueError("Invalid classified field")
        path, kind, claims = item["field_path"], item["kind"], item["claims"]
        if (not isinstance(path, str) or path not in texts or path in seen or item["text"] != texts[path]
                or not isinstance(kind, str) or kind not in _KINDS or not isinstance(claims, list)
                or len(claims) > 150 or any(not isinstance(c, str) or not c.strip() or c not in texts[path] for c in claims)
                or len(claims) != len(set(claims)) or (kind == "factual") != bool(claims)):
            raise ValueError("Unbound classified field")
        seen.add(path)
        expected.update((path, claim) for claim in claims)
        if kind == "uncertain" or (kind == "assumption" and not re.search(r"假设|推断|待验证|待确认", texts[path])):
            blockers.append(_blocked(path, texts[path], "coverage", status="needs_confirmation"))
        # A semantic reviewer cannot hide an obvious parameter behind 'planning'.
        # Exact model identity is already checked by server provenance.
        remainder = texts[path].replace(task["product_query"], "")
        for regex in (FACT_ASSERTION, _EXTRA_ASSERTION):
            for match in regex.finditer(remainder):
                assertion = match.group(0)
                if not any(canonical(assertion) in canonical(claim) for claim in claims):
                    blockers.append(_blocked(path, assertion, "coverage", status="needs_confirmation"))
    if seen != set(texts):
        raise ValueError("Incomplete final review coverage")
    mapping, mapped = [], set()
    for item in value["fact_claims"]:
        if not isinstance(item, dict) or set(item) != {"field_path", "claim", "fact_references"}:
            raise ValueError("Invalid final claim mapping")
        path, claim, refs = item["field_path"], item["claim"], item["fact_references"]
        if (not isinstance(path, str) or not isinstance(claim, str) or (path, claim) not in expected
                or (path, claim) in mapped or not isinstance(refs, list) or len(refs) > 50
                or any(not isinstance(ref, str) for ref in refs) or len(refs) != len(set(refs))):
            raise ValueError("Unbound final claim mapping")
        mapped.add((path, claim))
        # Keep a forged reference as an explicit blocking item, never drop it
        # and silently remap the claim to a different, legitimate fact.
        if set(refs) - eligible_ids:
            blockers.append(_blocked(path, claim, "invalid_reference"))
        mapping.append(copy.deepcopy(item))
    if mapped != expected:
        raise ValueError("Missing final factual statements")
    for item in value["issues"]:
        if (not isinstance(item, dict) or set(item) != {"field_path", "quote", "category"}
                or not isinstance(item["field_path"], str) or item["field_path"] not in texts
                or not isinstance(item["quote"], str) or not item["quote"].strip()
                or item["quote"] not in texts[item["field_path"]]
                or not isinstance(item["category"], str) or item["category"] not in {
                    "user_constraint", "strategy_mismatch", "exaggeration"}):
            raise ValueError("Unbound final issue")
        blockers.append(_blocked(item["field_path"], item["quote"], item["category"]))
    return mapping, blockers


def _local_issues(task: dict, content: dict, eligible_ids: set, allowed_sources: set) -> list:
    blockers = []
    for path, refs in [("fact_references", content.get("fact_references", []))] + [
        (f"images[{index}].fact_references", image.get("fact_references", [])) for index, image in enumerate(content["images"])
    ]:
        if set(refs) - eligible_ids:
            blockers.append(_blocked(path, "、".join(refs), "invalid_reference"))
    for index, image in enumerate(content["images"]):
        if image.get("source_ref") and image["source_ref"] not in allowed_sources:
            blockers.append(_blocked(f"images[{index}].source_ref", image["source_ref"], "invalid_reference"))
    for path, text in content_texts(content):
        if set(_CITATION.findall(text)) - eligible_ids:
            blockers.append(_blocked(path, text, "invalid_reference"))
        for match in _ABSOLUTE.finditer(text):
            blockers.append(_blocked(path, match.group(0), "exaggeration"))
        # Frequent explicit prohibitions have an independent guard as well as
        # semantic review. Bare words in a prohibition are not a sales claim.
        for pattern, forbidden in (
            (r"(?:不写|不要|不得|禁止|不添加).{0,20}(?:价格|优惠)", r"\d+(?:\.\d+)?\s*元|限时优惠|免费赠送"),
            (r"(?:不写|不要|不得|禁止).{0,20}(?:个人体验|第一人称)", r"我(?:用|买|体验)|亲测|实测"),
        ):
            if any(re.search(pattern, constraint) for constraint in task["constraints"]) and re.search(forbidden, text):
                blockers.append(_blocked(path, text, "user_constraint"))
        for scene in task["excluded_scenes"]:
            if scene and scene in text and not re.search(r"不(?:涉及|适用|包含)|排除", text):
                blockers.append(_blocked(path, text, "user_constraint"))
    return blockers


def _images(content: dict) -> dict:
    return {
        "status": "unknown", "visual_check_performed": False,
        "submitted_count": len(content["images"]), "confirmed_count": 0, "unknown_count": len(content["images"]),
        "items": [{"index": index, "name": image.get("name", ""), "status": "unknown",
                   "pixels": "unknown", "embedded_text": "unknown", "model_match": "unknown",
                   "caption_scope": "仅提交的说明文字纳入 text_check；未检查图片像素。"}
                  for index, image in enumerate(content["images"])],
        "missing_information": ["没有视觉识别或图片核验能力；图片外观、内嵌文字、型号对应与授权均未核验。"]
                               + (["未提交图片；空列表不代表图片核验通过。"] if not content["images"] else []),
    }


class FinalCheckService:
    def __init__(self, llm_client: Any = None, fact_checker: Any = None) -> None:
        self.llm_client, self.fact_checker = llm_client, fact_checker

    def check(self, task: dict, strategy: dict, eligible_facts: list, context: dict, content: dict) -> dict:
        content = validate_final_content(content)
        started, stages = time.perf_counter(), []
        stage = {"stage": "final_text_review", "model_call_count": 0, "upstream_request_count": 0}
        stages.append(stage)
        phase = time.perf_counter()
        try:
            client = self.llm_client or LLMClient(timeout=60)
            prompt = CLASSIFICATION_RULES + (Path(__file__).resolve().parents[2] / "prompts" / "final-check-system.md").read_text(encoding="utf-8-sig")
            payload = _review_request(task, strategy, eligible_facts, content)
            review = model_json(client, prompt, payload, stage)
            mapping, blockers = _validate_review(task, content, review, {r["fact_id"] for r in eligible_facts})
        except Exception as error:
            detail = safe_error_diagnostic(error)
            if isinstance(error, (ValueError, TypeError, KeyError)) and stage.get("status") == "ok":
                detail["failure_type"] = "response_schema"
            stage.update(detail, status="failed", elapsed_ms=round((time.perf_counter() - phase) * 1000, 2))
            suffix = {"timeout": "REQUEST_TIMEOUT", "connection": "CONNECTION_FAILED", "upstream_http": "UPSTREAM_HTTP_ERROR",
                      "json_parse": "JSON_INVALID", "response_schema": "RESPONSE_INVALID", "configuration": "CONFIGURATION_ERROR"}.get(detail["failure_type"], "FAILED")
            raise FinalCheckError("FINAL_CHECK_" + suffix, "最终文字审查未完成；成稿未被改写，未授予通过状态。", _diagnostics(stages, started)) from None
        stage["elapsed_ms"] = round((time.perf_counter() - phase) * 1000, 2)
        blockers.extend(_local_issues(task, content, {r["fact_id"] for r in eligible_facts},
                                      {r["source_ref"] for r in eligible_facts}))
        claims = [{"claim": item["claim"], "fact_references": item["fact_references"]} for item in mapping]
        checked = {"results": [], "errors": [], "warnings": [], "knowledge_source": copy.deepcopy(context.get("knowledge_source"))}
        if claims:
            phase = time.perf_counter()
            stage = {"stage": "final_fact_check", "model_call_count": 0, "upstream_request_count": 0}
            stages.append(stage)
            try:
                checked = (self.fact_checker or FactChecker(client)).check(task, claims, context)
                if not isinstance(checked, dict) or not isinstance(checked.get("results"), list) or len(checked["results"]) != len(claims):
                    raise ValueError("Invalid final fact checks")
                facts = {record["fact_id"]: record for record in context["retrieved_fact_records"]}
                for claim, result in zip(claims, checked["results"]):
                    validate_fact_check_result(result)
                    selected = [r for ref, r in facts.items() if ref in claim["fact_references"] or result["status"] == "conflicting"]
                    if (result["task_id"] != task["task_id"] or result["task_revision"] != task["revision"]
                            or result["claim"] != claim["claim"] or result.get("fact_references") != claim["fact_references"]
                            or any(text not in {r["evidence_text"] for r in selected} for text in result["evidence"])
                            or any(ref not in {r["source_ref"] for r in selected} for ref in result["source_refs"])):
                        raise ValueError("Unbound final fact check")
            except Exception as error:
                stage.update(safe_error_diagnostic(error), status="failed", elapsed_ms=round((time.perf_counter() - phase) * 1000, 2))
                raise FinalCheckError("FINAL_FACT_CHECK_FAILED", "最终事实核查未完成；未采信异常结果。", _diagnostics(stages, started)) from None
            stage.update(copy.deepcopy(checked.get("diagnostics", {})))
            stage["elapsed_ms"] = round((time.perf_counter() - phase) * 1000, 2)
        items = []
        for entry, result in zip(mapping, checked["results"]):
            items.append({"field_path": entry["field_path"], "check": result})
            if result["status"] != "supported":
                blockers.append({"field_path": entry["field_path"], "claim": result["claim"],
                                 "status": result["status"] if result["status"] != "not_applicable" else "needs_confirmation",
                                 "reason": result["reason"], "suggested_action": result["suggested_action"]})
        # Pure content advice and prohibitions remain auditable but do not gain
        # product-fact eligibility. A factual field is never exempted wholesale.
        for field in review["fields"]:
            if field["kind"] != "factual":
                items.append({"field_path": field["field_path"], "check": {
                    "task_id": task["task_id"], "task_revision": task["revision"], "claim": field["text"],
                    "status": "needs_confirmation" if field["kind"] == "uncertain" else "not_applicable",
                    "fact_references": [], "evidence": [], "source_refs": [],
                    "reason": ("无法可靠分类，不能授予通过状态。" if field["kind"] == "uncertain" else
                               "该文字属于表达建议、约束或明确标记的上下文/限制，不授予产品事实资格。"),
                    "suggested_action": "confirm" if field["kind"] == "uncertain" else "none",
                }})
        blockers = list({(b["field_path"], b["claim"], b["reason"]): b for b in blockers}.values())
        errors = copy.deepcopy(checked.get("errors", []))
        text_passed = not blockers and not errors
        text_status = "passed" if text_passed else (
            "blocked" if any(b["status"] in {"unsupported", "conflicting"} for b in blockers) else "needs_confirmation")
        return {
            "content_digest": content_digest(content), "execution_status": "partial" if errors else "completed",
            "text_check": {"status": text_status, "results": items, "blocking_items": blockers,
                           "counts": {status: sum(item["check"]["status"] == status for item in items) for status in CHECK_STATUSES}},
            "image_check": _images(content),
            "overall": {"status": "partial" if text_passed else "blocked", "completed": False,
                        "text_usable": text_passed, "ready_to_publish": False},
            "usable_text": {key: content[key] for key in ("title", "body", "cta", "plain_text")} if text_passed else None,
            "knowledge_source": copy.deepcopy(context.get("knowledge_source")),
            "warnings": list(dict.fromkeys(checked.get("warnings", []) + [
                "核查不改写用户成稿；不支持的事实必须删除或忠实改写后重新核查。",
                "文字通过不代表整套图文通过；图片视觉内容及内嵌文字仍为 unknown。",
            ] + (["本次采用本地副本 live=false，未进行实时在线核验。"] if (context.get("knowledge_source") or {}).get("live") is False else [])
              + (["部分来源类别为 other，可靠性有限，不能宣称官方认证。"] if any(r["source_type"] == "other" for r in eligible_facts) else [])
              + (["资料未注明有效期，当前有效性未知；检索时间不是发布时间。"] if any(r["valid_until"] is None for r in eligible_facts) else []))),
            "errors": errors, "diagnostics": _diagnostics(stages, started),
            "next_action": "verify_images" if text_passed else "revise_content_and_recheck",
        }
