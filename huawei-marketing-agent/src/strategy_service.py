"""Generate and evidence-check a single promotion strategy draft."""

from __future__ import annotations

import json
import copy
import math
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

from .fact_checker import FactChecker, canonical
from .llm_client import LLMClient, LLMClientError, model_json, safe_error_diagnostic
from .v2_contracts import ContractValidationError, validate_strategy_draft
from .statement_review import FACT_ASSERTION as _FACT_ASSERTION, CLASSIFICATION_RULES


# Assertion spans, not a sentence classifier. Single words such as "采用" or
# "支持" prove nothing. Every field still receives independent semantic review,
# including text with no match here. Clear facts cannot hide in planning text.
_ROOT_KEYS = {"strategy", "fact_claims"}
_SCALAR_PATHS = {
    "task_summary", "topic", "audience.description", "audience.basis", "audience_need",
    "core_message", "content_angle", "content_format", "cta",
}


class StrategyServiceError(RuntimeError):
    def __init__(self, code: str, message: str, *, diagnostics: Optional[dict] = None,
                 http_status: int = 502) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.diagnostics = diagnostics or {}
        self.http_status = http_status


def strategy_timeout_seconds() -> float:
    """Read strategy-only configuration at call time; never change other clients."""
    try:
        value = float(os.environ.get("STRATEGY_LLM_TIMEOUT_SECONDS", "120"))
        if not math.isfinite(value) or value <= 0:
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        raise StrategyServiceError(
            "STRATEGY_CONFIGURATION_ERROR",
            "STRATEGY_LLM_TIMEOUT_SECONDS 必须为有限正数；未发起策略请求。",
        ) from None
    return value


def _generation_payload(task: dict, eligible_facts: list, research_context: dict) -> dict:
    """Explicit projection: no dialogue, raw documents, unchecked facts or examples."""
    source = research_context.get("knowledge_source") or {}
    return {
        "task": {key: task[key] for key in (
            "product_query", "audience", "platform", "goal", "scene", "constraints", "excluded_scenes",
        )},
        # Structured time, store and usage are user/opportunity context only;
        # contract validation keeps them explicitly unverified.
        "scenario_inputs": copy.deepcopy(task.get("scenario_inputs", {})),
        "source_limits": {
            "knowledge_source": {key: source[key] for key in ("mode", "name", "live", "status") if key in source},
            "warnings": list(dict.fromkeys(
                (["本地副本 live=false，不能宣称实时在线核验。"] if source.get("live") is False else [])
                + (["部分来源类别为 other，不能宣称官方认证。"]
                   if any(record["source_type"] == "other" for record in eligible_facts) else [])
                + (["未注明有效期的记录当前有效性未知，检索时间不是发布时间。"]
                   if any(record["valid_until"] is None for record in eligible_facts) else [])
            )),
        },
        "eligible_fact_records": [{key: record[key] for key in (
            "fact_id", "product_model", "claim", "evidence_text", "source_ref", "source_type",
            "retrieved_at", "valid_until",
        )} for record in eligible_facts],
    }


def _request_size(system_prompt: str, payload: dict) -> dict:
    # Count the exact first upstream message strings, including the client suffix.
    return {
        "system_prompt_chars": len(system_prompt + "\nReturn a JSON object."),
        "payload_chars": len(json.dumps(payload, ensure_ascii=False, allow_nan=False)),
        "fact_count": len(payload["eligible_fact_records"]),
        "history_turn_count": 0,
    }


def _trace_snapshot(stages: list, started: float) -> dict:
    return {"elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "model_call_count": sum(stage.get("model_call_count", 0) for stage in stages),
            "upstream_request_count": sum(stage.get("upstream_request_count", 0) for stage in stages),
            "stages": stages}


def _stage(stages: list, name: str, attempt: int) -> dict:
    value = {"stage": name, "strategy_attempt": attempt, "model_call_count": 0,
             "upstream_request_count": 0, "upstream_requests": [], "elapsed_ms": 0.0}
    stages.append(value)
    return value


def _call_failure(error: Exception, diagnostic: dict, stages: list, started: float) -> StrategyServiceError:
    # No exception message, request data or response body enters diagnostics.
    diagnostic.update(status="failed", **safe_error_diagnostic(error))
    category = diagnostic["failure_type"]
    code, description = {
        "connection": ("STRATEGY_CONNECTION_FAILED", "LLM 连接失败"),
        "timeout": ("STRATEGY_REQUEST_TIMEOUT", "LLM 请求超时"),
        "upstream_http": ("STRATEGY_UPSTREAM_HTTP_ERROR", "LLM 上游 HTTP 错误"),
        "json_parse": ("STRATEGY_JSON_INVALID", "模型 JSON 解析失败"),
        "response_schema": ("STRATEGY_RESPONSE_INVALID", "模型响应结构无效"),
        "configuration": ("STRATEGY_CONFIGURATION_ERROR", "模型配置无效"),
        "refused": ("STRATEGY_MODEL_REFUSED", "模型拒绝请求"),
        "response_size": ("STRATEGY_RESPONSE_INVALID", "模型响应超过大小限制"),
        "client_error": ("STRATEGY_CLIENT_ERROR", "模型客户端调用失败"),
    }.get(category, ("STRATEGY_INTERNAL_ERROR", "策略程序内部异常"))
    detail = _safe_llm_detail(error)
    return StrategyServiceError(code, f"{description}{detail}；策略未保存，任务与已核查事实已保留。",
                                diagnostics=_trace_snapshot(stages, started),
                                http_status=500 if category == "internal" else 502)


def _safe_llm_detail(error: Exception) -> str:
    """Expose only a validated HTTP status or allowlisted client error category."""
    if not isinstance(error, LLMClientError):
        return ""
    status = error.status_code
    if isinstance(status, int) and not isinstance(status, bool) and 100 <= status <= 599:
        return f"（LLM HTTP {status}；服务响应详情已隐藏）"
    safe_categories = {
        "LLM request timed out": "（LLM 请求超时）",
        "Unable to reach the configured LLM service; connection details were withheld": "（LLM 服务不可达）",
        "LLM connection failed; connection details were withheld": "（LLM 连接失败）",
        "LLM request could not be sent safely; configuration details were withheld": "（LLM 请求配置无效）",
        "The model did not return a valid JSON object after one format retry": "（模型未返回有效 JSON）",
        "The model did not return a JSON object": "（模型未返回 JSON 对象）",
        "LLM returned an unexpected response structure": "（LLM 响应结构异常）",
        "LLM response did not include generated content": "（LLM 响应缺少生成内容）",
        "LLM response did not include generated text": "（LLM 响应缺少文本）",
        "The model declined the request": "（模型拒绝了请求）",
        "LLM response exceeded the permitted size": "（LLM 响应超过大小限制）",
    }
    return safe_categories.get(str(error), "")


def _prompt() -> str:
    configured = os.environ.get("STRATEGY_PROMPT_PATH", "").strip()
    candidates = ([Path(configured).expanduser()] if configured else [])
    candidates.append(Path(__file__).resolve().parents[2] / "prompts" / "strategy-system.md")
    for path in candidates:
        try:
            content = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError, ValueError):
            continue
        if content.strip():
            return content
    raise StrategyServiceError("STRATEGY_PROMPT_UNAVAILABLE", "策略提示词不可用；未生成或保存策略。")


def _resolve_path(draft: dict, field_path: str) -> Optional[str]:
    if field_path in _SCALAR_PATHS:
        if field_path.startswith("audience."):
            return draft["audience"][field_path.split(".", 1)[1]]
        return draft[field_path]
    match = re.fullmatch(r"content_outline\[(\d+)\]\.(section|purpose)", field_path)
    if match:
        index = int(match.group(1))
        if index < len(draft["content_outline"]):
            return draft["content_outline"][index][match.group(2)]
    match = re.fullmatch(r"(assumptions|pending_confirmations|risk_notes)\[(\d+)\]", field_path)
    if match:
        values = draft[match.group(1)]
        index = int(match.group(2))
        if index < len(values):
            return values[index]
    return None


def _public_texts(draft: dict) -> list:
    values = [(path, _resolve_path(draft, path)) for path in sorted(_SCALAR_PATHS)]
    for index, section in enumerate(draft["content_outline"]):
        values.extend((
            (f"content_outline[{index}].section", section["section"]),
            (f"content_outline[{index}].purpose", section["purpose"]),
        ))
    for field in ("assumptions", "pending_confirmations", "risk_notes"):
        values.extend((f"{field}[{index}]", item) for index, item in enumerate(draft[field]))
    return [(path, value) for path, value in values if isinstance(value, str) and value.strip()]


def _normalize_claim_map(draft: dict, value: Any, eligible_ids: set, product_model: str = "") -> list:
    if not isinstance(value, list) or len(value) > 100:
        raise ValueError("fact_claims 必须是有限长度数组。")
    normalized = []
    seen = set()
    used_ids = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"field_path", "claim", "fact_references"}:
            raise ValueError("fact_claims 项结构无效。")
        path, claim, references = item["field_path"], item["claim"], item["fact_references"]
        target = _resolve_path(draft, path) if isinstance(path, str) else None
        if target is None:
            raise ValueError("策略事实映射的 field_path 无法定位到实际策略字段。")
        if not isinstance(claim, str) or not claim.strip() or len(claim) > 8000 or claim not in target:
            raise ValueError("策略事实映射的 claim 必须是对应字段中的连续原文；请复制策略字段原句，不要改写。")
        if (not isinstance(references, list) or any(not isinstance(ref, str) for ref in references)
                or len(references) != len(set(references))):
            raise ValueError("fact_claims.fact_references 格式无效。")
        if any(ref not in eligible_ids for ref in references):
            raise ValueError("策略引用了没有当前使用资格的事实。")
        key = (path, claim, tuple(references))
        if key in seen:
            raise ValueError("策略事实映射重复。")
        seen.add(key)
        used_ids.update(references)
        normalized.append({"field_path": path, "claim": claim, "fact_references": list(references)})

    declared_ids = set(draft["fact_references"])
    if declared_ids != used_ids:
        raise ValueError("Strategy.fact_references 必须与逐项事实核查引用完全一致。")
    for index, section in enumerate(draft["content_outline"]):
        mapped = {ref for entry in normalized
                  if entry["field_path"].startswith(f"content_outline[{index}].")
                  for ref in entry["fact_references"]}
        if set(section["fact_references"]) != mapped:
            raise ValueError("内容结构中的事实引用必须与其逐项核查映射一致。")

    uncovered = []
    by_path = {}
    for entry in normalized:
        by_path.setdefault(entry["field_path"], []).append(canonical(entry["claim"]))
    for path, text in _public_texts(draft):
        # Repeating the exact task model is identity, not a new parameter claim.
        text_without_model = text.replace(product_model, "") if product_model else text
        for match in _FACT_ASSERTION.finditer(text_without_model):
            assertion = match.group(0)
            if not any(
                canonical(assertion) in claim for claim in by_path.get(path, [])
            ):
                uncovered.append({"field_path": path, "claim": assertion.strip()[:500],
                                  "status": "unsupported", "reason": "字段中的可核验事实子句未映射到当前可用证据。",
                                  "suggested_action": "单独提取完整事实及限定条件并绑定可用证据，或删除该断言。"})
    if uncovered:
        raise ClaimCoverageError(uncovered)
    return normalized


def validate_claim_map(draft: dict, value: Any, eligible_ids: set, product_model: str) -> list:
    """Revalidate a saved mapping without making a model call."""
    return _normalize_claim_map(draft, value, eligible_ids, product_model)


_AUDIT_PROMPT = CLASSIFICATION_RULES + """你是独立的策略事实表达审查器，不生成策略、不确认策略。审查 fields 全部字段。
仅返回 {"fields":[{"field_path":"输入路径","text":"输入的完整字段值","kind":"factual|planning|constraint|user_context|assumption|limitation|uncertain","claims":["逐字完整事实子句"]}]}。
必须覆盖输入 fields 的所有路径，禁止新增、遗漏或改写 text。"""


def _audit_coverage(client: Any, task: dict, draft: dict, claim_map: list, diagnostic: dict) -> dict:
    texts = dict(_public_texts(draft))
    review = model_json(client, _AUDIT_PROMPT, {
        "task_context": {key: task[key] for key in ("product_query", "audience", "scene", "platform", "goal")},
        "scenario_inputs": copy.deepcopy(task.get("scenario_inputs", {})),
        "fields": [{"field_path": path, "text": text} for path, text in texts.items()],
        "declared_fact_claims": claim_map,
    }, diagnostic)
    validate_coverage_review(task, draft, claim_map, review)
    return review


def validate_coverage_review(task: dict, draft: dict, claim_map: list, review: Any) -> None:
    """Check every audited field and its binding, also when saving a strategy."""
    texts = dict(_public_texts(draft))
    try:
        if not isinstance(review, dict) or set(review) != {"fields"} or not isinstance(review["fields"], list):
            raise ValueError
        seen, blockers = set(), []
        for item in review["fields"]:
            if not isinstance(item, dict) or set(item) != {"field_path", "text", "kind", "claims"}:
                raise ValueError
            path, kind, claims = item["field_path"], item["kind"], item["claims"]
            if (not isinstance(path, str) or path not in texts or path in seen or item["text"] != texts[path]
                    or kind not in {"factual", "planning", "constraint", "user_context", "assumption", "limitation", "uncertain"}
                    or not isinstance(claims, list) or len(claims) > 100
                    or any(not isinstance(claim, str) or not claim.strip() or claim not in texts[path] for claim in claims)
                    or (kind == "factual") != bool(claims)):
                raise ValueError
            seen.add(path)
            if kind == "uncertain":
                blockers.append({"field_path": path, "claim": texts[path], "status": "needs_confirmation",
                                 "reason": "无法可靠区分事实断言与规划或推断，未自动放行。",
                                 "suggested_action": "明确事实与规划边界，补充依据或请用户确认后重新核查。"})
            mapped = [entry["claim"] for entry in claim_map if entry["field_path"] == path]
            for claim in claims:
                if not any(canonical(claim) in canonical(entry) for entry in mapped):
                    blockers.append({"field_path": path, "claim": claim, "status": "unsupported",
                                     "reason": "全文独立审查发现未绑定可用事实的断言。",
                                     "suggested_action": "删除断言或逐项绑定完整的可用原文并重新核查。"})
            if kind == "assumption" and not (
                path.startswith(("assumptions[", "pending_confirmations["))
                or any(texts[path] in value for value in draft["assumptions"])
            ):
                blockers.append({"field_path": path, "claim": texts[path], "status": "needs_confirmation",
                                 "reason": "该推断未明确写入 assumptions。", "suggested_action": "将推断及其确认边界写入 assumptions。"})
        if seen != set(texts):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise StrategyServiceError("STRATEGY_CHECK_INVALID", "策略全文审查结构无效或字段覆盖不完整；策略未保存。") from None
    if draft["audience"]["basis_type"] == "user_provided" and draft["audience"]["description"] != task["audience"]:
        blockers.append({"field_path": "audience.description", "claim": draft["audience"]["description"],
                         "status": "unsupported", "reason": "受众与当前用户确认的受众不一致。", "suggested_action": "恢复用户已确认的受众。"})
    if draft["audience_need"] not in draft["assumptions"]:
        blockers.append({"field_path": "audience_need", "claim": draft["audience_need"], "status": "needs_confirmation",
                         "reason": "受众需求解释须作为推断保留在 assumptions 中，不能伪装成已知行为。",
                         "suggested_action": "将 audience_need 原样写入 assumptions，并说明仍待具体人群确认。"})
    if blockers:
        raise ClaimCoverageError(blockers)


class ClaimCoverageError(ValueError):
    def __init__(self, items: list) -> None:
        super().__init__("策略中存在未映射的产品事实表达。")
        self.items = items


def review_confirmation_gaps(task: dict, draft: dict, eligible_facts: list, context: dict) -> tuple:
    """Resolve only a proven model-link reminder; keep real gaps blocking.

Eligibility alone is not enough: independently check the stored original and
model association. Source freshness/reliability stays a limitation, not a
fictional official/current certification.
"""
    value, blockers = copy.deepcopy(draft), []
    records = {record["fact_id"]: record for record in eligible_facts}
    originals = {record["fact_id"]: record for record in context.get("retrieved_fact_records", [])}
    verified = bool(draft["fact_references"])
    for ref in draft["fact_references"]:
        record, original = records.get(ref), originals.get(ref)
        if (not record or not original or any(record[k] != original[k] for k in original if k != "status")
                or FactChecker._provenance(original, context.get("evidence_documents", []), task["product_query"]) is not None):
            verified = False
    remaining = []
    for index, text in enumerate(value["pending_confirmations"]):
        model_link = bool(re.search(r"(?:型号.*(?:对应|关联)|(?:对应|关联).*型号)", text)
                          and re.search(r"引用|记录|来源|证据|资料", text))
        display_advice = bool(re.search(r"(?:引用|来源).{0,8}(?:格式|展示|标注方式)", text))
        critical = model_link or bool(re.search(r"确认|待核|未验证|未核实", text)
                                      and re.search(r"配置|参数|事实|型号|证据是否|原文是否", text)
                                      and not display_advice)
        if model_link and verified:
            note = "已核对引用记录与当前指定型号及本次原文快照的对应关系；来源时效与可靠性限制仍保留，不代表实时或官方认证。"
            if note not in value["risk_notes"]:
                value["risk_notes"].append(note)
        elif critical:
            remaining.append(text)
            blockers.append({"field_path": f"pending_confirmations[{index}]", "claim": text,
                             "status": "needs_confirmation", "reason": "策略仍存在关键型号、配置或证据关联缺口，不能用用户确认替代事实核查。",
                             "suggested_action": "补全并核查关键依据后重新生成策略。"})
        else:
            remaining.append(text)
    value["pending_confirmations"] = remaining
    if not verified:
        blockers.append({"field_path": "fact_references", "claim": "引用记录与当前型号的关联未验证。",
                         "status": "needs_confirmation", "reason": "缺少有效的同型号原资料对应关系。",
                         "suggested_action": "重新检索并核查原资料，不能确认当前策略。"})
    return value, blockers


class StrategyService:
    """LLM strategy generation with bounded repair and server fact checking."""

    def __init__(self, llm_client: Any = None, fact_checker: Any = None) -> None:
        self.llm_client = llm_client
        self.fact_checker = fact_checker

    def generate(self, task: dict, eligible_facts: list, research_context: dict) -> dict:
        started, stages = time.perf_counter(), []
        if not eligible_facts:
            raise StrategyServiceError("NO_VERIFIED_FACTS", "当前没有通过核查且适用的产品事实；请补充资料并重新核查。")
        setup = _stage(stages, "setup", 0)
        try:
            timeout = strategy_timeout_seconds()
            client = self.llm_client or LLMClient(timeout=timeout)
            checker = self.fact_checker or FactChecker(client)
            system_prompt = _prompt()
            setup["request_timeout_seconds"] = getattr(client, "timeout", timeout)
        except StrategyServiceError as error:
            setup.update(status="failed", failure_type="configuration")
            error.diagnostics = _trace_snapshot(stages, started)
            raise
        except Exception as error:
            raise _call_failure(error, setup, stages, started) from None
        setup["status"] = "ok"
        eligible_ids = {record["fact_id"] for record in eligible_facts}
        payload = _generation_payload(task, eligible_facts, research_context)
        previous = None
        for attempt in range(2):
            request = dict(payload)
            if previous is not None:
                request["strategy_to_repair"] = previous["draft"]
                request["blocking_items"] = previous["blocking_items"]
            active = _stage(stages, "initial_generation" if attempt == 0 else "repair", attempt + 1)
            active["request_size"] = _request_size(system_prompt, request)
            try:
                raw = model_json(client, system_prompt, request, active)
            except Exception as error:
                raise _call_failure(error, active, stages, started) from None
            try:
                if not isinstance(raw, dict) or set(raw) != _ROOT_KEYS:
                    raise ValueError("模型返回字段不符合策略内部输出契约。")
                draft = validate_strategy_draft(raw["strategy"], eligible_ids)
                draft, gaps = review_confirmation_gaps(task, draft, eligible_facts, research_context)
                if gaps:
                    raise ClaimCoverageError(gaps)
                claim_map = _normalize_claim_map(draft, raw["fact_claims"], eligible_ids, task["product_query"])
                if not claim_map:
                    raise ClaimCoverageError([{
                        "field_path": "fact_claims", "claim": "策略没有提供任何事实映射。",
                        "status": "unsupported", "reason": "策略未将可用产品事实绑定到具体表达。",
                        "suggested_action": "为策略中的事实性表达添加逐字引用，或删除产品事实表达。",
                    }])
                active = _stage(stages, "strategy_audit", attempt + 1)
                try:
                    coverage = _audit_coverage(client, task, draft, claim_map, active)
                except (ClaimCoverageError, StrategyServiceError):
                    raise
                except Exception as error:
                    raise _call_failure(error, active, stages, started) from None
                active = _stage(stages, "fact_check", attempt + 1)
                checked_started = time.perf_counter()
                try:
                    checks = checker.check(task, [{
                        "claim": entry["claim"], "fact_references": entry["fact_references"],
                    } for entry in claim_map], research_context)
                except Exception as error:
                    raise _call_failure(error, active, stages, started) from None
                finally:
                    active["elapsed_ms"] = round((time.perf_counter() - checked_started) * 1000, 2)
                if isinstance(checks, dict) and isinstance(checks.get("diagnostics"), dict):
                    active.update(checks["diagnostics"])
                active.setdefault("status", "ok")
                check_results = checks.get("results") if isinstance(checks, dict) else None
                if not isinstance(check_results, list) or len(check_results) != len(claim_map):
                    raise StrategyServiceError("STRATEGY_CHECK_INVALID", "策略事实核查返回格式无效；策略未保存，请稍后重试。")
                if checks.get("errors"):
                    category = active.get("failure_type", "internal")
                    failure = LLMClientError("Semantic checking failed", category=category,
                                             status_code=active.get("http_status"),
                                             exception_types=active.get("exception_types"))
                    raise _call_failure(failure, active, stages, started)
                blocking = []
                fact_by_id = {record["fact_id"]: record for record in eligible_facts}
                for entry, result in zip(claim_map, check_results):
                    allowed_records = [fact_by_id[ref] for ref in entry["fact_references"]]
                    if (not isinstance(result, dict)
                            or result.get("claim") != entry["claim"]
                            or result.get("task_id") != task["task_id"]
                            or result.get("task_revision") != task["revision"]
                            or result.get("fact_references") != entry["fact_references"]
                            or any(value not in {record["evidence_text"] for record in allowed_records}
                                   for value in result.get("evidence", []))
                            or any(value not in {record["source_ref"] for record in allowed_records}
                                   for value in result.get("source_refs", []))):
                        raise StrategyServiceError("STRATEGY_CHECK_INVALID", "策略核查未绑定当前任务证据；策略未保存。")
                    if result.get("status") == "supported" and (not result.get("evidence") or not result.get("source_refs")):
                        raise StrategyServiceError("STRATEGY_CHECK_INVALID", "策略核查缺少对应证据或来源；策略未保存。")
                    if result.get("status") != "supported":
                        blocking.append({
                            "field_path": entry["field_path"], "claim": entry["claim"][:500],
                            "status": result.get("status", "needs_confirmation"),
                            "reason": result.get("reason", "事实核查未完成。"),
                            "suggested_action": result.get("suggested_action", "confirm"),
                        })
                if not blocking:
                    return {"status": "passed", "draft": draft, "fact_claims": claim_map,
                            "coverage_review": coverage, "fact_check": checks,
                            "attempts": attempt + 1, "blocking_items": [],
                            "diagnostics": _trace_snapshot(stages, started)}
                active.update(status="blocked", failure_type="fact_blocked")
                previous = {"draft": draft, "blocking_items": blocking, "fact_check": checks, "failure_type": "fact_blocked"}
            except ClaimCoverageError as error:
                active.update(status="blocked", failure_type="fact_blocked")
                previous = {"draft": raw.get("strategy", {}) if isinstance(raw, dict) else {},
                            "blocking_items": error.items, "failure_type": "fact_blocked"}
            except StrategyServiceError as error:
                if error.code == "STRATEGY_CHECK_INVALID":
                    active.update(status="failed", failure_type="response_schema", exception_types=["ContractValidationError"])
                if not error.diagnostics:
                    error.diagnostics = _trace_snapshot(stages, started)
                raise
            except (ContractValidationError, ValueError, TypeError, KeyError) as error:
                reason = (
                    str(error)[:300]
                    if isinstance(error, (ContractValidationError, ValueError))
                    else "模型返回的策略字段类型或结构无效。"
                )
                active.update(status="blocked", failure_type="response_schema",
                              exception_types=safe_error_diagnostic(error)["exception_types"])
                previous = {"draft": raw.get("strategy", {}) if isinstance(raw, dict) else {},
                            "failure_type": "response_schema",
                            "blocking_items": [{
                                "field_path": "strategy", "claim": "", "status": "unsupported",
                                "reason": reason or "策略字段、事实映射或引用不符合契约。",
                                "suggested_action": "按契约修正策略字段和事实引用，或删除无依据表达。",
                            }]}
            if attempt == 1:
                break
            system_prompt += "\n\n只修复 blocking_items 指出的策略字段。重新检查全部对外事实。不要改变任务和服务器字段，不要使用允许资料之外的事实。"
        return {"status": "blocked", "draft": previous["draft"] if previous else {},
                "fact_claims": [], "fact_check": previous.get("fact_check") if previous else None,
                "attempts": 2, "blocking_items": previous["blocking_items"] if previous else [],
                "failure_type": previous.get("failure_type", "fact_blocked") if previous else "fact_blocked",
                "diagnostics": _trace_snapshot(stages, started)}
