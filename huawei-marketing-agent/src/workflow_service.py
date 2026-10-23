"""Small in-process workflow service for the v2 agent contracts.

It owns task identity, revisions and response snapshots. Requirements are
interpreted through the configured LLM and product facts are retrieved outside
the repository lock. Pre-generation and strategy checks bind to that retrieval
snapshot; final text checks also bind the exact submitted content and strategy.
"""

from __future__ import annotations

import copy
import json
import re
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .requirements_service import RequirementsError, interpret_requirements
from .product_research_service import ProductResearchService
from .fact_checker import FactChecker, canonical, is_expired
from .strategy_service import (StrategyService, StrategyServiceError, validate_claim_map,
                               validate_coverage_review, review_confirmation_gaps)
from .final_content_contracts import validate_final_content, content_digest, content_texts
from .final_check_service import FinalCheckService, FinalCheckError
from .v2_contracts import (
    FIELD_NAMES,
    MAX_TEXT_LENGTH,
    ContractValidationError,
    Strategy,
    TaskContext,
    validate_fact_record,
    validate_fact_check_result,
    validate_strategy,
    validate_strategy_draft,
    validate_task_context,
)


V2_ROUTES = {
    "/api/agent/understand",
    "/api/agent/continue",
    "/api/agent/research",
    "/api/strategy/generate",
    "/api/strategy/confirm",
    "/api/strategy/handoff",
    "/api/facts/check",
    "/api/facts/check-final",
}
CORE_FIELDS = ("product_query", "audience", "platform", "goal", "scene")
UPDATE_FIELDS = set(FIELD_NAMES)


def _missing_requirements(task: TaskContext) -> List[str]:
    # An intentionally cleared scene is optional; never restore it from history.
    return [field for field in CORE_FIELDS
            if task["field_status"][field] != "confirmed"
            and not (field == "scene" and task["field_status"][field] == "cleared")]


def _question(task: TaskContext) -> List[str]:
    questions = {
        "product_query": "这次要推广的产品或具体型号是什么？",
        "audience": "这次内容主要面向哪类人群？",
        "platform": "这次内容准备发布在哪个平台？",
        "goal": "这次推广最希望达成什么目标？",
        "scene": "这次推广对应什么使用或营销场景？",
    }
    missing = _missing_requirements(task)
    return [questions[missing[0]]] if missing else []


class WorkflowError(Exception):
    """Safe, structured error raised by the in-process service."""

    def __init__(self, code: str, message: str, *, data: Any = None, http_status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data
        self.http_status = http_status


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _text(value: Any, name: str, allow_empty: bool = True) -> str:
    if not isinstance(value, str) or len(value) > MAX_TEXT_LENGTH or (not allow_empty and not value.strip()):
        raise WorkflowError("INVALID_REQUEST", f"{name} 必须是长度不超过 {MAX_TEXT_LENGTH} 的文本。")
    return value


def _object(value: Any, name: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise WorkflowError("INVALID_REQUEST", f"{name} 必须是 JSON 对象。")
    return value


def _list_of_text(value: Any, name: str) -> List[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or len(item) > MAX_TEXT_LENGTH for item in value):
        raise WorkflowError("INVALID_REQUEST", f"{name} 必须是文本数组。")
    return list(value)


def _copy(value: Any) -> Any:
    return copy.deepcopy(value)


def _envelope(data: Any = None, error: Any = None, success: bool = True) -> Dict[str, Any]:
    return {"success": success, "data": _copy(data), "error": _copy(error)}


def _error(error: WorkflowError) -> Dict[str, Any]:
    detail = {"code": error.code, "message": error.message}
    if error.data is not None:
        detail["details"] = _copy(error.data)
    return _envelope(None, detail, False)


class TaskRepository:
    """Thread-safe in-memory task store with optimistic revision checks."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._tasks: Dict[str, TaskContext] = {}
        self._strategies: Dict[str, Dict[str, Strategy]] = {}
        self._strategy_versions: Dict[str, int] = {}
        self._research_contexts: Dict[str, dict] = {}
        self._fact_checks: Dict[str, list] = {}
        self._strategy_checks: Dict[str, Dict[str, dict]] = {}
        self._strategy_history: Dict[str, list] = {}
        self._final_checks: Dict[str, list] = {}
        self._final_contents: Dict[str, dict] = {}

    def _snapshot(self, task: TaskContext) -> TaskContext:
        # Validate before returning so corrupted internal state cannot escape.
        validate_task_context(task)
        return _copy(task)

    def create(self, payload: Dict[str, Any]) -> TaskContext:
        with self._lock:
            source = payload.get("source", "direct")
            if source not in {"direct", "opportunity"}:
                raise WorkflowError("INVALID_REQUEST", "source 只能是 direct 或 opportunity。")
            user_input = _text(payload.get("user_input", ""), "user_input")
            opportunity = payload.get("opportunity_context")
            if source == "opportunity" and not isinstance(opportunity, dict):
                raise WorkflowError("INVALID_REQUEST", "opportunity 来源任务必须提供 opportunity_context。")
            if opportunity is not None and not isinstance(opportunity, dict):
                raise WorkflowError("INVALID_REQUEST", "opportunity_context 必须是对象或 null。")
            values: Dict[str, Any] = {}
            statuses: Dict[str, str] = {}
            for field in FIELD_NAMES:
                if field == "constraints":
                    value = payload.get(field, [])
                    value = _list_of_text(value, field)
                    values[field] = value
                    statuses[field] = "confirmed" if value else "unset"
                else:
                    value = _text(payload.get(field, ""), field)
                    values[field] = value
                    statuses[field] = "confirmed" if value.strip() else "unset"
            task: TaskContext = {
                "task_id": "task-" + uuid.uuid4().hex,
                "revision": 1,
                "source": source,
                "user_input": user_input,
                "conversation": ([{"role": "user", "text": user_input, "at": _now()}] if user_input.strip() else []),
                **values,
                "field_status": statuses,
                "excluded_scenes": _list_of_text(payload.get("excluded_scenes", []), "excluded_scenes"),
                "opportunity_context": _copy(opportunity),
                "fact_records": [],
                "current_strategy_id": None,
                "current_strategy_version": None,
                # Field completeness is not proof that understanding or retrieval ran.
                "workflow_status": "collecting_requirements",
            }
            validate_task_context(task)
            self._tasks[task["task_id"]] = task
            self._strategies[task["task_id"]] = {}
            self._strategy_versions[task["task_id"]] = 0
            self._fact_checks[task["task_id"]] = []
            self._strategy_checks[task["task_id"]] = {}
            self._strategy_history[task["task_id"]] = []
            self._final_checks[task["task_id"]] = []
            return self._snapshot(task)

    def get(self, task_id: str) -> TaskContext:
        _text(task_id, "task_id", allow_empty=False)
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise WorkflowError("TASK_NOT_FOUND", "任务不存在或已过期。", http_status=404)
            return self._snapshot(task)

    def append_user_turn(self, task_id: str, expected_revision: Any, turn_text: str) -> TaskContext:
        """Persist a continue turn before external work, using optimistic revisioning."""
        _text(turn_text, "user_input", allow_empty=False)
        with self._lock:
            task = self._checked_task(task_id, expected_revision)
            next_task = _copy(task)
            next_task["conversation"].append({"role": "user", "text": turn_text, "at": _now()})
            next_task["revision"] += 1
            self._tasks[task_id] = next_task
            return self._snapshot(next_task)

    def apply_interpretation(
        self,
        task_id: str,
        expected_revision: Any,
        updates: Dict[str, Any],
        clear_fields: List[str],
        excluded_scenes: List[str],
        summary: str,
        question: Optional[str],
    ) -> Tuple[TaskContext, Dict[str, Any]]:
        """Commit validated model suggestions only if its input snapshot is current."""
        if not isinstance(updates, dict) or set(updates) - UPDATE_FIELDS:
            raise WorkflowError("INVALID_MODEL_RESPONSE", "需求理解结果包含不支持的字段。", http_status=502)
        if not isinstance(clear_fields, list) or set(clear_fields) - UPDATE_FIELDS or set(updates) & set(clear_fields):
            raise WorkflowError("INVALID_MODEL_RESPONSE", "需求理解清空字段与更新字段冲突。", http_status=502)
        _text(summary, "summary", allow_empty=False)
        if question is not None:
            _text(question, "question", allow_empty=False)
        _list_of_text(excluded_scenes, "excluded_scenes")

        with self._lock:
            task = self._checked_task(task_id, expected_revision)
            next_task = _copy(task)
            for field, value in updates.items():
                if field == "constraints":
                    value = _list_of_text(value, field)
                else:
                    value = _text(value, field, allow_empty=False)
                next_task[field] = value
                next_task["field_status"][field] = "confirmed"
            for field in clear_fields:
                next_task[field] = [] if field == "constraints" else ""
                next_task["field_status"][field] = "cleared"
            changed = any(next_task[field] != task[field] for field in FIELD_NAMES)
            product_changed = next_task["product_query"] != task["product_query"]
            if changed or excluded_scenes or next_task["current_strategy_id"]:
                self._supersede_current_strategy(task_id, next_task)
                if product_changed:
                    self._invalidate_checks(task_id, next_task, drop_research=True)
            if product_changed:
                next_task["fact_records"] = []
            next_task["excluded_scenes"] = list(dict.fromkeys(next_task["excluded_scenes"] + excluded_scenes))
            missing = _missing_requirements(next_task)
            next_task["workflow_status"] = "collecting_requirements" if missing else "ready_for_strategy"
            # Model questions are advisory. Select one missing field on the
            # server, so a model cannot ask several questions or re-ask a known field.
            questions = _question(next_task)
            assistant_turn = summary + (("\n" + questions[0]) if questions else "")
            next_task["conversation"].append({"role": "assistant", "text": assistant_turn, "at": _now()})
            next_task["revision"] += 1
            validate_task_context(next_task)
            self._tasks[task_id] = next_task
            data = {
                "summary": summary,
                "questions": questions,
                "missing_information": missing,
                "next_action": "collecting_requirements" if missing else "research_product",
                "understanding_status": "needs_input" if missing else "complete",
            }
            return self._snapshot(next_task), data

    def update(self, task_id: str, expected_revision: Any, payload: Dict[str, Any]) -> TaskContext:
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 1:
            raise WorkflowError("INVALID_REQUEST", "expected_revision 必须是正整数。")
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise WorkflowError("TASK_NOT_FOUND", "任务不存在或已过期。", http_status=404)
            if task["revision"] != expected_revision:
                raise WorkflowError(
                    "VERSION_CONFLICT", "任务版本已变化，请基于最新快照重试。",
                    data={"task_id": task_id, "current_revision": task["revision"], "task": self._snapshot(task)},
                    http_status=409,
                )
            next_task = _copy(task)
            allowed = {"task_id", "expected_revision", "user_input", "updates", "clear_fields", "excluded_scenes"}
            if set(payload) - allowed:
                raise WorkflowError("INVALID_REQUEST", "continue 请求包含不支持的字段。")
            turn_text = _text(payload.get("user_input", ""), "user_input")
            if not turn_text.strip() and not payload.get("updates") and not payload.get("clear_fields"):
                raise WorkflowError("INVALID_REQUEST", "continue 至少需要 user_input、updates 或 clear_fields。")
            if turn_text.strip():
                next_task["conversation"].append({"role": "user", "text": turn_text, "at": _now()})
            updates = payload.get("updates", {})
            if not isinstance(updates, dict):
                raise WorkflowError("INVALID_REQUEST", "updates 必须是对象。")
            unknown = set(updates) - UPDATE_FIELDS
            if unknown:
                raise WorkflowError("INVALID_REQUEST", "updates 包含不支持的字段。", data={"fields": sorted(unknown)})
            clears = payload.get("clear_fields", [])
            clears = _list_of_text(clears, "clear_fields")
            unknown_clears = set(clears) - UPDATE_FIELDS
            if unknown_clears:
                raise WorkflowError("INVALID_REQUEST", "clear_fields 包含不支持的字段。", data={"fields": sorted(unknown_clears)})
            if set(updates) & set(clears):
                raise WorkflowError("INVALID_REQUEST", "同一字段不能同时更新和清空。")
            for field, value in updates.items():
                if field == "constraints":
                    value = _list_of_text(value, field)
                    if not value:
                        raise WorkflowError("INVALID_REQUEST", "请使用 clear_fields 显式清空 constraints。")
                else:
                    value = _text(value, field, allow_empty=False)
                next_task[field] = value
                next_task["field_status"][field] = "confirmed"
            for field in clears:
                next_task[field] = [] if field == "constraints" else ""
                next_task["field_status"][field] = "cleared"
            if "excluded_scenes" in payload:
                next_task["excluded_scenes"] = _list_of_text(payload["excluded_scenes"], "excluded_scenes")
            if next_task["product_query"] != task["product_query"]:
                next_task["fact_records"] = []
                self._invalidate_checks(task_id, next_task, drop_research=True)
            self._supersede_current_strategy(task_id, next_task)
            next_task["current_strategy_id"] = None
            next_task["current_strategy_version"] = None
            next_task["revision"] += 1
            next_task["workflow_status"] = "collecting_requirements"
            validate_task_context(next_task)
            self._tasks[task_id] = next_task
            return self._snapshot(next_task)

    def begin_research(self, task_id: str, expected_revision: Any) -> TaskContext:
        with self._lock:
            task = self._checked_task(task_id, expected_revision)
            if task["workflow_status"] not in {"collecting_requirements", "ready_for_strategy", "failed"}:
                raise WorkflowError("INVALID_TRANSITION", "当前任务状态不能开始产品检索。", http_status=409)
            if task["field_status"]["product_query"] != "confirmed":
                raise WorkflowError("PRODUCT_REQUIRED", "开始产品检索前需要确认产品或型号。", http_status=409)
            missing = _missing_requirements(task)
            if missing:
                raise WorkflowError(
                    "REQUIREMENTS_INCOMPLETE", "开始产品检索前，请先补齐必要的需求字段。",
                    data={"missing_information": missing}, http_status=409,
                )
            next_task = _copy(task)
            self._supersede_current_strategy(task_id, next_task)
            self._invalidate_checks(task_id, next_task, drop_research=True)
            for fact in next_task["fact_records"]:
                fact["status"] = "stale"
            next_task["workflow_status"] = "researching"
            next_task["revision"] += 1
            self._tasks[task_id] = next_task
            return self._snapshot(next_task)

    def complete_research(
        self,
        task_id: str,
        expected_revision: Any,
        fact_records: Any,
        *,
        expected_product_query: Optional[str] = None,
        knowledge_source: Optional[dict] = None,
        evidence_documents: Optional[list] = None,
    ) -> TaskContext:
        if not isinstance(fact_records, list) or len(fact_records) > 500:
            raise WorkflowError("INVALID_REQUEST", "fact_records 必须是有限长度数组。")
        try:
            records = [validate_fact_record(item) for item in fact_records]
            # Retrieval cannot grant check eligibility, even if an upstream
            # caller accidentally supplies an old supported label.
            for record in records:
                record["status"] = "stale" if is_expired(record) else "retrieved"
        except ContractValidationError as error:
            raise WorkflowError("INVALID_CONTRACT", str(error)) from error
        ids = [item["fact_id"] for item in records]
        if len(ids) != len(set(ids)):
            raise WorkflowError("INVALID_CONTRACT", "fact_records.fact_id 不能重复。")
        product_models = {item["product_model"] for item in records}
        if len(product_models) > 1:
            raise WorkflowError("PRODUCT_MODEL_CONFLICT", "同一任务不能混合多个精确产品型号的资料。", http_status=409)
        with self._lock:
            task = self._checked_task(task_id, expected_revision)
            if task["workflow_status"] != "researching":
                raise WorkflowError("INVALID_TRANSITION", "只有 researching 任务可以完成检索。", http_status=409)
            if expected_product_query is not None and task["product_query"] != expected_product_query:
                raise WorkflowError("VERSION_CONFLICT", "检索期间产品型号已变化，已丢弃过期结果。", http_status=409)
            if records and any(not self._same_product_model(task["product_query"], model) for model in product_models):
                raise WorkflowError("PRODUCT_MODEL_CONFLICT", "检索事实与当前任务的精确产品型号不一致。", http_status=409)
            next_task = _copy(task)
            next_task["fact_records"] = _copy(records)
            next_task["workflow_status"] = "ready_for_strategy"
            next_task["revision"] += 1
            self._invalidate_checks(task_id, next_task, drop_research=True)
            self._research_contexts[task_id] = {
                "evidence_revision": next_task["revision"],
                "product_query": task["product_query"],
                "knowledge_source": _copy(knowledge_source),
                "retrieved_fact_records": _copy(records),
                "evidence_documents": _copy(evidence_documents or []),
            }
            self._tasks[task_id] = next_task
            return self._snapshot(next_task)

    def _invalidate_checks(self, task_id: str, next_task: dict, *, drop_research: bool = False) -> None:
        """Called under the repository lock; keep the audit basis in memory."""
        self._invalidate_final_checks(task_id)
        for check in self._fact_checks.get(task_id, []):
            check["valid"] = False
        for audit in self._strategy_checks.get(task_id, {}).values():
            audit["valid"] = False
        for record in next_task["fact_records"]:
            if record["status"] != "stale":
                record["status"] = "retrieved"
        if drop_research:
            self._research_contexts.pop(task_id, None)

    def _supersede_current_strategy(self, task_id: str, next_task: dict) -> None:
        self._invalidate_final_checks(task_id)
        strategy_id = next_task.get("current_strategy_id")
        if strategy_id:
            strategy = self._strategies[task_id].get(strategy_id)
            if strategy:
                self._strategy_history[task_id].append(_copy(strategy))
                strategy["confirmation_status"] = "superseded"
                strategy["confirmed_at_task_revision"] = None
            audit = self._strategy_checks.get(task_id, {}).get(strategy_id)
            if audit:
                audit["valid"] = False
        next_task["current_strategy_id"] = None
        next_task["current_strategy_version"] = None

    def _invalidate_final_checks(self, task_id: str) -> None:
        for audit in self._final_checks.get(task_id, []):
            audit["valid"] = False
        if task_id in self._final_contents:
            self._final_contents[task_id]["active"] = False

    def fact_check_snapshot(self, task_id: str, expected_revision: Any) -> Tuple[dict, dict]:
        with self._lock:
            task = self._checked_task(task_id, expected_revision)
            if task["field_status"]["product_query"] != "confirmed":
                raise WorkflowError("PRODUCT_REQUIRED", "事实核查前需要明确产品型号。", http_status=409)
            if task["workflow_status"] in {"researching", "failed"}:
                raise WorkflowError("WORKFLOW_NOT_READY", "请先完成有效的产品检索。", http_status=409)
            return self._snapshot(task), _copy(self._research_contexts.get(task_id, {}))

    def get_fact_checks(self, task_id: str) -> list:
        """Read-only audit snapshots; evidence remains bound to its old revision."""
        with self._lock:
            self.get(task_id)
            return _copy(self._fact_checks.get(task_id, []))

    def _eligible_fact_ids(self, task: dict) -> set:
        records = {record["fact_id"]: record for record in task["fact_records"]}
        eligible, blocked = set(), set()
        for batch in self._fact_checks.get(task["task_id"], []):
            if not batch["valid"]:
                continue
            blocked.update(batch["blocked_fact_ids"])
            for result in batch["results"]:
                refs = result["fact_references"]
                if len(refs) == 1 and refs[0] in records and canonical(result["claim"]) == canonical(records[refs[0]]["claim"]):
                    if result["status"] == "supported":
                        eligible.add(refs[0])
                    else:
                        eligible.discard(refs[0])
        return {ref for ref in eligible - blocked
                if records[ref]["status"] == "supported" and not is_expired(records[ref])}

    def complete_fact_check(self, task: dict, context: dict, claims: list, assessment: dict) -> Tuple[dict, dict]:
        """Commit only after external work, atomically rechecking task and evidence."""
        with self._lock:
            current = self._checked_task(task["task_id"], task["revision"])
            active = self._research_contexts.get(task["task_id"], {})
            if current["product_query"] != task["product_query"] or active != context:
                raise WorkflowError("VERSION_CONFLICT", "核查期间产品或证据已变化，过期结果未保存。", http_status=409)
            results = assessment.get("results")
            if not isinstance(results, list) or len(results) != len(claims):
                raise WorkflowError("INVALID_FACT_CHECK_RESULT", "核查结果结构无效，未保存结果。", http_status=502)
            known = {r["fact_id"]: r for r in current["fact_records"]}
            snapshots = context.get("retrieved_fact_records", [])
            for request, result in zip(claims, results):
                validate_fact_check_result(result)
                if (result["task_id"] != task["task_id"] or result["task_revision"] != task["revision"]
                        or result["claim"] != request["claim"] or result.get("fact_references") != request["fact_references"]):
                    raise WorkflowError("INVALID_FACT_CHECK_RESULT", "核查结果与原请求绑定不一致。", http_status=502)
                allowed = [r for r in snapshots if r["fact_id"] in request["fact_references"] or result["status"] == "conflicting"]
                if any(text not in {r["evidence_text"] for r in allowed} for text in result["evidence"]):
                    raise WorkflowError("INVALID_FACT_CHECK_RESULT", "核查引用了快照外的证据。", http_status=502)
                if any(ref not in {r["source_ref"] for r in allowed} for ref in result["source_refs"]):
                    raise WorkflowError("INVALID_FACT_CHECK_RESULT", "核查引用了快照外的来源。", http_status=502)
            next_task = _copy(current)
            updates = {}
            rank = {"supported": 0, "not_applicable": 1, "needs_confirmation": 2, "unsupported": 3, "conflicting": 4}
            for result in results:
                refs = result["fact_references"]
                if len(refs) == 1 and refs[0] in known and canonical(result["claim"]) == canonical(known[refs[0]]["claim"]):
                    previous = updates.get(refs[0])
                    if previous is None or rank[result["status"]] > rank[previous]:
                        updates[refs[0]] = result["status"]
            blocked = set(assessment.get("blocked_fact_ids", []))
            for record in next_task["fact_records"]:
                if record["fact_id"] in blocked:
                    record["status"] = "conflicting"
                elif record["fact_id"] in updates:
                    status = updates[record["fact_id"]]
                    record["status"] = "needs_confirmation" if status == "not_applicable" else status
            if current["current_strategy_id"]:
                self._supersede_current_strategy(task["task_id"], next_task)
                next_task["workflow_status"] = "collecting_requirements" if _missing_requirements(next_task) else "ready_for_strategy"
            next_task["revision"] += 1
            batch = {
                **_copy(assessment), "check_id": "check-" + uuid.uuid4().hex,
                "task_id": task["task_id"], "task_revision": task["revision"],
                "saved_task_revision": next_task["revision"],
                "evidence_revision": context.get("evidence_revision"),
                "product_model": task["product_query"], "checked_at": _now(), "valid": True,
            }
            validate_task_context(next_task)
            self._fact_checks[task["task_id"]].append(batch)
            batch["eligible_fact_ids"] = sorted(self._eligible_fact_ids(next_task))
            batch["next_action"] = ("retry_fact_check" if batch["errors"] else
                                    "generate_strategy" if batch["eligible_fact_ids"] else "confirm_or_research_evidence")
            self._tasks[task["task_id"]] = next_task
            public_batch = _copy(batch)
            # Preserve original retrieval records for audit after a re-research
            # or product change, without serializing another full snapshot.
            batch["retrieved_fact_records"] = _copy(snapshots)
            return self._snapshot(next_task), public_batch

    @staticmethod
    def _same_product_model(left: str, right: str) -> bool:
        normalize = lambda value: re.sub(
            r"[\W_]+", "", re.sub(r"^HUAWEI\s*", "", value.strip(), flags=re.I).casefold(),
        )
        return normalize(left) == normalize(right)

    def fail_task(self, task_id: str, expected_revision: Any) -> TaskContext:
        with self._lock:
            task = self._checked_task(task_id, expected_revision)
            next_task = _copy(task)
            next_task["workflow_status"] = "failed"
            next_task["revision"] += 1
            self._tasks[task_id] = next_task
            return self._snapshot(next_task)

    def strategy_snapshot(self, task_id: str, expected_revision: Any) -> Tuple[dict, dict, list]:
        """Take a short-lock snapshot; caller performs all model work outside it."""
        with self._lock:
            task = self._checked_task(task_id, expected_revision)
            if task["workflow_status"] not in {"ready_for_strategy", "awaiting_user_confirmation", "strategy_confirmed"} or _missing_requirements(task):
                raise WorkflowError("WORKFLOW_NOT_READY", "请先完成有效需求理解和产品检索。", http_status=409)
            eligible = self._eligible_fact_ids(task)
            if not eligible:
                raise WorkflowError("NO_VERIFIED_FACTS", "没有通过核查且仍适用的事实；请补充资料或核查当前候选事实。", http_status=409)
            context = self._research_contexts.get(task_id)
            if not context:
                raise WorkflowError("NO_VERIFIED_FACTS", "缺少当前检索依据；请重新检索并核查。", http_status=409)
            return self._snapshot(task), _copy(context), _copy([record for record in task["fact_records"] if record["fact_id"] in eligible])

    def add_strategy(self, task_id: str, expected_revision: Any, draft: Any, *, assessment: Optional[dict] = None,
                     context: Optional[dict] = None) -> Tuple[TaskContext, Strategy]:
        with self._lock:
            task = self._checked_task(task_id, expected_revision)
            if task["workflow_status"] not in {"ready_for_strategy", "awaiting_user_confirmation", "strategy_confirmed"}:
                raise WorkflowError("WORKFLOW_NOT_READY", "任务尚未完成检索，不能生成策略。", http_status=409)
            fact_ids = self._eligible_fact_ids(task)
            try:
                checked = validate_strategy_draft(draft, fact_ids)
            except ContractValidationError as error:
                raise WorkflowError("INVALID_STRATEGY", str(error)) from error
            self._validate_strategy_assessment(task, checked, assessment, context)
            if self._strategy_versions[task_id] >= 10000:
                raise WorkflowError("VERSION_LIMIT", "单个任务的策略版本已达上限。", http_status=409)
            version = self._strategy_versions[task_id] + 1
            strategy: Strategy = {
                **_copy(checked),
                "strategy_id": "strategy-" + uuid.uuid4().hex,
                "task_id": task_id,
                "task_revision": task["revision"],
                "strategy_version": version,
                "confirmation_status": "pending",
                "confirmed_at_task_revision": None,
            }
            validate_strategy(strategy, fact_ids)
            next_task = _copy(task)
            self._supersede_current_strategy(task_id, next_task)
            next_task["revision"] += 1
            next_task["workflow_status"] = "awaiting_user_confirmation"
            next_task["current_strategy_id"] = strategy["strategy_id"]
            next_task["current_strategy_version"] = version
            self._tasks[task_id] = next_task
            self._strategies[task_id][strategy["strategy_id"]] = strategy
            self._strategy_versions[task_id] = version
            self._strategy_history[task_id].append(_copy(strategy))
            self._strategy_checks[task_id][strategy["strategy_id"]] = {
                **_copy(assessment), "draft": _copy(checked), "valid": True,
                "strategy_id": strategy["strategy_id"], "strategy_version": version,
                "task_id": task_id, "task_revision": task["revision"], "checked_at": _now(),
                "evidence_revision": context["evidence_revision"],
            }
            return self._snapshot(next_task), _copy(strategy)

    def _validate_strategy_assessment(self, task: dict, draft: dict, assessment: Any, context: Any) -> None:
        if (not isinstance(assessment, dict) or assessment.get("status") != "passed"
                or assessment.get("draft") != draft or assessment.get("blocking_items")
                or type(assessment.get("attempts")) is not int or assessment["attempts"] not in {1, 2}):
            raise WorkflowError("STRATEGY_CHECK_REQUIRED", "策略必须通过本任务的完整生成后核查才能保存或确认。", http_status=409)
        active = self._research_contexts.get(task["task_id"])
        if context is None or not active or active != context or active.get("product_query") != task["product_query"]:
            raise WorkflowError("VERSION_CONFLICT", "策略生成期间产品或证据已变化，未保存过期结果。", http_status=409)
        _, gaps = review_confirmation_gaps(task, draft, task["fact_records"], context)
        if gaps:
            raise WorkflowError("STRATEGY_CONFIRMATION_BLOCKED", "型号或关键事实仍有确认缺口，不能保存为可确认策略。",
                                data={"blocking_items": gaps}, http_status=409)
        try:
            mapping = validate_claim_map(draft, assessment.get("fact_claims"), self._eligible_fact_ids(task), task["product_query"])
            validate_coverage_review(task, draft, mapping, assessment["coverage_review"])
            if not mapping:
                raise ValueError
            checked = assessment["fact_check"]
            if checked.get("errors") or len(checked["results"]) != len(mapping):
                raise ValueError
            records = {record["fact_id"]: record for record in context["retrieved_fact_records"]}
            for entry, result in zip(mapping, checked["results"]):
                validate_fact_check_result(result)
                selected = [records[ref] for ref in entry["fact_references"]]
                if (result["status"] != "supported" or result["task_id"] != task["task_id"]
                        or result["task_revision"] != task["revision"] or result["claim"] != entry["claim"]
                        or result.get("fact_references") != entry["fact_references"]
                        or any(text not in {record["evidence_text"] for record in selected} for text in result["evidence"])
                        or any(ref not in {record["source_ref"] for record in selected} for ref in result["source_refs"])):
                    raise ValueError
        except (ValueError, TypeError, KeyError, AttributeError, StrategyServiceError):
            raise WorkflowError("STRATEGY_CHECK_REQUIRED", "策略核查凭据无效或未绑定当前任务证据，未保存策略。", http_status=409) from None

    def get_strategy_check(self, task_id: str, strategy_id: str) -> dict:
        with self._lock:
            self.get(task_id)
            return _copy(self._strategy_checks.get(task_id, {}).get(strategy_id, {}))

    def get_strategy_history(self, task_id: str) -> list:
        with self._lock:
            self.get(task_id)
            return _copy(self._strategy_history[task_id])

    def _check_current_strategy(self, task: dict, strategy: dict) -> dict:
        audit = self._strategy_checks.get(task["task_id"], {}).get(strategy["strategy_id"])
        context = self._research_contexts.get(task["task_id"], {})
        draft = {key: strategy[key] for key in audit["draft"]} if audit else {}
        if (not audit or not audit["valid"] or draft != audit["draft"]
                or audit["evidence_revision"] != context.get("evidence_revision")
                or not set(strategy["fact_references"]) <= self._eligible_fact_ids(task)):
            raise WorkflowError("STRATEGY_CHECK_REQUIRED", "当前策略核查或所用事实已失效，需重新生成并确认。", http_status=409)
        _, gaps = review_confirmation_gaps(task, draft, task["fact_records"], context)
        if gaps:
            raise WorkflowError("STRATEGY_CONFIRMATION_BLOCKED", "关键型号、配置或证据缺口未解决，不能确认或使用该策略。",
                                data={"blocking_items": gaps}, http_status=409)
        return audit

    def get_current_strategy(self, task_id: str) -> Optional[Strategy]:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise WorkflowError("TASK_NOT_FOUND", "任务不存在或已过期。", http_status=404)
            strategy_id = task["current_strategy_id"]
            strategy = self._strategies[task_id].get(strategy_id) if strategy_id else None
            return _copy(strategy) if strategy else None

    def confirm_strategy(self, task_id: str, expected_revision: Any, strategy_id: Any, strategy_version: Any) -> Tuple[TaskContext, Strategy]:
        if not isinstance(strategy_id, str) or not strategy_id.strip():
            raise WorkflowError("INVALID_REQUEST", "strategy_id 必须是非空文本。")
        if isinstance(strategy_version, bool) or not isinstance(strategy_version, int) or strategy_version < 1:
            raise WorkflowError("INVALID_REQUEST", "strategy_version 必须是正整数。")
        with self._lock:
            task = self._checked_task(task_id, expected_revision)
            strategy = self._strategies[task_id].get(strategy_id)
            if (not strategy or task["current_strategy_id"] != strategy_id
                    or task["current_strategy_version"] != strategy_version
                    or strategy["strategy_version"] != strategy_version
                    or strategy["confirmation_status"] != "pending"):
                raise WorkflowError("STRATEGY_VERSION_CONFLICT", "策略 ID 或版本已失效，不能确认。", http_status=409)
            self._check_current_strategy(task, strategy)
            next_task = _copy(task)
            next_task["revision"] += 1
            next_task["workflow_status"] = "strategy_confirmed"
            self._strategy_history[task_id].append(_copy(strategy))
            strategy["confirmation_status"] = "confirmed"
            strategy["confirmed_at_task_revision"] = next_task["revision"]
            self._tasks[task_id] = next_task
            self._strategy_history[task_id].append(_copy(strategy))
            return self._snapshot(next_task), _copy(strategy)

    def creative_handoff(self, task_id: str, expected_revision: Any, strategy_id: Any, strategy_version: Any) -> dict:
        """Return only adopted eligible evidence; never return raw retrieval bodies."""
        if not isinstance(strategy_id, str) or not strategy_id.strip():
            raise WorkflowError("INVALID_REQUEST", "strategy_id 必须是非空文本。")
        if isinstance(strategy_version, bool) or not isinstance(strategy_version, int) or strategy_version < 1:
            raise WorkflowError("INVALID_REQUEST", "strategy_version 必须是正整数。")
        with self._lock:
            task = self._checked_task(task_id, expected_revision)
            strategy = self.get_current_strategy(task_id)
            if (not strategy or strategy["strategy_id"] != strategy_id
                    or strategy["strategy_version"] != strategy_version
                    or strategy["confirmation_status"] != "confirmed" or task["workflow_status"] != "strategy_confirmed"):
                raise WorkflowError("STRATEGY_NOT_CONFIRMED", "交接必须绑定当前已确认的有效策略 ID 和版本。", http_status=409)
            audit = self._check_current_strategy(task, strategy)
            ids = set(strategy["fact_references"])
            adopted = [record for record in task["fact_records"] if record["fact_id"] in ids]
            public_task = self._snapshot(task)
            public_task["fact_records"] = _copy(adopted)
            context = self._research_contexts[task_id]
            valid_checks = [{
                "check_id": batch["check_id"], "task_revision": batch["task_revision"],
                "evidence_revision": batch["evidence_revision"], "knowledge_source": batch["knowledge_source"],
                "warnings": batch["warnings"],
                "results": [item for item in batch["results"] if item["status"] == "supported"
                            and item["fact_references"] and set(item["fact_references"]) <= ids],
            } for batch in self._fact_checks[task_id] if batch["valid"] and any(
                item["status"] == "supported" and item["fact_references"] and set(item["fact_references"]) <= ids
                for item in batch["results"])]
            return _copy({
                "task": public_task, "strategy": strategy, "fact_records": adopted,
                "fact_checks": valid_checks, "strategy_check": audit,
                "knowledge_source": context["knowledge_source"],
                "source_limits": list(dict.fromkeys(w for batch in valid_checks for w in batch["warnings"])),
                "platform_requirements": {"platform": task["platform"], "content_format": strategy["content_format"]},
                "user_constraints": task["constraints"], "pending_confirmations": strategy["pending_confirmations"],
                "images": [], "image_status": "unknown",
                "warnings": ["本阶段未核验图片；空列表不代表已确认有可用图片。"],
            })

    def begin_final_check(self, task_id: str, expected_revision: Any, strategy_id: Any,
                          strategy_version: Any, content: dict) -> tuple:
        """Register an edit before model work; any previous content check expires."""
        content = validate_final_content(content)
        with self._lock:
            # Reuse the same confirmation and provenance gate as the handoff.
            handoff = self.creative_handoff(task_id, expected_revision, strategy_id, strategy_version)
            task = self._tasks[task_id]
            previous_version = self._final_contents.get(task_id, {}).get("content_version", 0)
            self._invalidate_final_checks(task_id)
            next_task = _copy(task)
            next_task["revision"] += 1
            binding = {
                "request_id": "final-request-" + uuid.uuid4().hex,
                "strategy_id": strategy_id, "strategy_version": strategy_version,
                "content_version": previous_version + 1, "content_digest": content_digest(content),
                "active": True,
            }
            self._final_contents[task_id] = {**_copy(binding), "content": _copy(content)}
            self._tasks[task_id] = next_task
            return (self._snapshot(next_task), _copy(self._research_contexts[task_id]),
                    handoff["strategy"], handoff["fact_records"], binding)

    def assert_final_current(self, task: dict, context: dict, binding: dict) -> dict:
        with self._lock:
            current = self._checked_task(task["task_id"], task["revision"])
            active = self._final_contents.get(task["task_id"], {})
            if (current["product_query"] != task["product_query"]
                    or self._research_contexts.get(task["task_id"]) != context
                    or not active.get("active") or any(active.get(key) != value for key, value in binding.items())):
                raise WorkflowError("VERSION_CONFLICT", "成稿、策略或证据已改变，过期核查结果未保存。", http_status=409)
            self.creative_handoff(current["task_id"], current["revision"], binding["strategy_id"], binding["strategy_version"])
            return self._snapshot(current)

    def complete_final_check(self, task: dict, context: dict, binding: dict, content: dict,
                             assessment: dict) -> tuple:
        with self._lock:
            current = self.assert_final_current(task, context, binding)
            self._validate_final_assessment(task, context, content, assessment)
            next_task = _copy(current)
            next_task["revision"] += 1
            audit = {
                **_copy(assessment), "check_id": "final-check-" + uuid.uuid4().hex,
                "task_id": task["task_id"], "task_revision": task["revision"],
                "saved_task_revision": next_task["revision"],
                "strategy_id": binding["strategy_id"], "strategy_version": binding["strategy_version"],
                "content_version": binding["content_version"], "evidence_revision": context["evidence_revision"],
                "checked_at": _now(), "valid": True,
            }
            self._tasks[task["task_id"]] = next_task
            self._final_checks[task["task_id"]].append(audit)
            return self._snapshot(next_task), _copy(audit)

    def _validate_final_assessment(self, task: dict, context: dict, content: dict, assessment: Any) -> None:
        """Do not let malformed service results grant text or visual approval."""
        try:
            if assessment["content_digest"] != content_digest(content):
                raise ValueError
            text, image, overall = (assessment[key] for key in ("text_check", "image_check", "overall"))
            if text["status"] not in {"passed", "blocked", "needs_confirmation"}:
                raise ValueError
            paths = dict(content_texts(content))
            records = context["retrieved_fact_records"]
            covered = set()
            for item in text["results"]:
                result, path = item["check"], item["field_path"]
                validate_fact_check_result(result)
                if (path not in paths or result["claim"] not in paths[path]
                        or result["task_id"] != task["task_id"] or result["task_revision"] != task["revision"]):
                    raise ValueError
                allowed = [r for r in records if r["fact_id"] in result.get("fact_references", []) or result["status"] == "conflicting"]
                if (any(e not in {r["evidence_text"] for r in allowed} for e in result["evidence"])
                        or any(s not in {r["source_ref"] for r in allowed} for s in result["source_refs"])):
                    raise ValueError
                if result["status"] == "supported" and (not result["evidence"] or not result["source_refs"]):
                    raise ValueError
                covered.add(path)
            if covered != set(paths):
                raise ValueError
            passed = (not text["blocking_items"] and not assessment["errors"]
                      and all(item["check"]["status"] in {"supported", "not_applicable"} for item in text["results"]))
            if ((text["status"] == "passed") != passed or overall["text_usable"] != passed
                    or overall["status"] != ("partial" if passed else "blocked")
                    or overall["completed"] is not False or overall["ready_to_publish"] is not False
                    or image["status"] != "unknown" or image["visual_check_performed"] is not False
                    or image["confirmed_count"] != 0 or image["unknown_count"] != len(content["images"])
                    or assessment["usable_text"] != ({k: content[k] for k in ("title", "body", "cta", "plain_text")} if passed else None)):
                raise ValueError
        except (ValueError, KeyError, TypeError, ContractValidationError):
            raise WorkflowError("INVALID_FINAL_CHECK_RESULT", "最终核查结果未正确绑定成稿及当前证据，未保存。", http_status=502) from None

    def get_final_checks(self, task_id: str, *, content: Optional[dict] = None) -> list:
        """Audit snapshots; callers must also compare the exact content digest."""
        with self._lock:
            task = self.get(task_id)
            audits = _copy(self._final_checks.get(task_id, []))
            active = self._final_contents.get(task_id, {})
            for audit in audits:
                audit["valid"] = bool(audit["valid"] and active.get("active")
                    and audit["content_digest"] == active.get("content_digest")
                    and audit["strategy_id"] == task["current_strategy_id"]
                    and audit["strategy_version"] == task["current_strategy_version"]
                    and (content is None or audit["content_digest"] == content_digest(validate_final_content(content))))
            return audits

    def _checked_task(self, task_id: str, expected_revision: Any) -> TaskContext:
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 1:
            raise WorkflowError("INVALID_REQUEST", "expected_revision 必须是正整数。")
        task = self._tasks.get(task_id)
        if task is None:
            raise WorkflowError("TASK_NOT_FOUND", "任务不存在或已过期。", http_status=404)
        if task["revision"] != expected_revision:
            raise WorkflowError(
                "VERSION_CONFLICT", "任务版本已变化，请基于最新快照重试。",
                data={"task_id": task_id, "current_revision": task["revision"], "task": self._snapshot(task)},
                http_status=409,
            )
        return task


REPOSITORY = TaskRepository()
RESEARCH_SERVICE: Any = ProductResearchService()
FACT_CHECKER: Any = FactChecker()
STRATEGY_SERVICE: Any = None
FINAL_CHECK_SERVICE: Any = None


def reset_repository() -> None:
    """Clear only the process-local store; intended for isolated offline tests."""
    global REPOSITORY
    REPOSITORY = TaskRepository()


def set_repository(repository: TaskRepository) -> None:
    """Replace the process-local repository, primarily for isolated tests."""
    if not isinstance(repository, TaskRepository):
        raise TypeError("repository must be a TaskRepository")
    global REPOSITORY
    REPOSITORY = repository


def set_research_service(service: Any) -> None:
    """Inject the product research adapter, primarily for offline fixtures."""
    global RESEARCH_SERVICE
    RESEARCH_SERVICE = service


def set_fact_checker(checker: Any) -> None:
    """Inject a checker/client for offline tests; production never uses fixtures."""
    global FACT_CHECKER
    FACT_CHECKER = checker


def set_strategy_service(service: Any) -> None:
    """Inject a strategy service for offline tests; None restores real service."""
    global STRATEGY_SERVICE
    STRATEGY_SERVICE = service


def set_final_check_service(service: Any) -> None:
    """Inject a final reviewer only for explicit offline fixtures."""
    global FINAL_CHECK_SERVICE
    FINAL_CHECK_SERVICE = service


def _require_task(payload: Dict[str, Any]) -> Tuple[TaskContext, int]:
    task_id = _text(payload.get("task_id", ""), "task_id", allow_empty=False)
    expected = payload.get("expected_revision")
    task = REPOSITORY.get(task_id)
    if isinstance(expected, bool) or not isinstance(expected, int) or expected < 1:
        raise WorkflowError("INVALID_REQUEST", "expected_revision 必须是正整数。")
    if task["revision"] != expected:
        raise WorkflowError("VERSION_CONFLICT", "任务版本已变化，请基于最新快照重试。", data={"current_revision": task["revision"], "task": task}, http_status=409)
    return task, expected


def _not_implemented(task: Optional[TaskContext], capability: str) -> Dict[str, Any]:
    return _envelope(
        {"workflow_status": task["workflow_status"] if task else None, "task": task, "capability": capability},
        {"code": "NOT_IMPLEMENTED", "message": f"{capability} 尚未接入真实服务；本接口未执行该步骤。"},
        False,
    )


def _model_failure(task: TaskContext, error: RequirementsError) -> Tuple[int, Dict[str, Any]]:
    return error.http_status, {
        "success": False,
        "data": {"task": task, "recovery": "修复模型或提示词配置后，基于返回的最新 task.revision 重试。"},
        "error": {"code": error.code, "message": error.message},
    }


def _apply_understanding(task: TaskContext, turn: str, explicit_updates: Dict[str, Any], explicit_clears: List[str]) -> Tuple[TaskContext, Dict[str, Any]]:
    try:
        result = interpret_requirements(task, turn, explicit_updates, explicit_clears)
    except RequirementsError:
        raise
    except Exception:
        raise RequirementsError(
            "UNDERSTANDING_FAILED",
            "需求理解暂时失败；当前任务已保存，请稍后基于最新 revision 重试。",
            502,
        ) from None

    # The model may suggest a change only when its exact value is grounded in
    # the current user turn, an explicit form edit, or opportunity metadata.
    def grounded(value: str, source_text: str = turn) -> bool:
        compact_source = re.sub(r"\s+", "", source_text.casefold())
        compact_value = re.sub(r"\s+", "", value.casefold())
        return bool(compact_value) and compact_value in compact_source

    updates: Dict[str, Any] = {}
    for field, value in result["updates"].items():
        if field in explicit_updates or field in explicit_clears:
            continue
        values = value if field == "constraints" else [value]
        # Opportunity metadata can fill unset fields, but cannot replace user
        # edits or restore a cleared field during a later turn.
        opportunity_value = (task["opportunity_context"] or {}).get(field)
        from_opportunity = (task["source"] == "opportunity"
                            and task["field_status"][field] == "unset"
                            and value == opportunity_value)
        if from_opportunity or all(grounded(item) for item in values):
            updates[field] = value

    # Explicit structured clears own field status. A model cannot clear a
    # previously confirmed value unless the caller explicitly requested it.
    clears = [field for field in result["clear_fields"] if field in explicit_clears]
    if set(clears) & set(updates):
        updates = {field: value for field, value in updates.items() if field not in clears}
    excluded = [item for item in result["excluded_scenes"] if grounded(item)]

    return REPOSITORY.apply_interpretation(
        task["task_id"], task["revision"], updates, clears, excluded,
        result["summary"], result["question"],
    )


def dispatch(path: str, payload: Any) -> Tuple[int, Dict[str, Any]]:
    """Handle one v2 request and return ``(HTTP status, envelope)``."""
    try:
        body = _object(payload, "请求体")
        if path == "/api/agent/understand":
            allowed = set(FIELD_NAMES) | {"source", "user_input", "opportunity_context", "excluded_scenes"}
            if set(body) - allowed:
                raise WorkflowError("INVALID_REQUEST", "understand 请求包含服务端管理字段或未知字段。")
            task = REPOSITORY.create(body)
            explicit_updates = {
                field: task[field] for field in FIELD_NAMES
                if (field == "constraints" and task[field]) or (field != "constraints" and task[field].strip())
            }
            try:
                task, understood = _apply_understanding(task, task["user_input"], explicit_updates, [])
            except RequirementsError as error:
                return _model_failure(REPOSITORY.get(task["task_id"]), error)
            return 201, _envelope({
                "task": task,
                "understanding": {
                    "implementation_status": "IMPLEMENTED",
                    "summary": understood["summary"],
                    "questions": understood["questions"],
                },
                "missing_information": understood["missing_information"],
                "next_action": understood["next_action"],
            })
        if path == "/api/agent/continue":
            task_id = _text(body.get("task_id", ""), "task_id", allow_empty=False)
            task = REPOSITORY.update(task_id, body.get("expected_revision"), body)
            explicit_updates = body.get("updates", {})
            explicit_clears = body.get("clear_fields", [])
            turn = body.get("user_input", "")
            try:
                task, understood = _apply_understanding(task, turn, explicit_updates, explicit_clears)
            except RequirementsError as error:
                return _model_failure(REPOSITORY.get(task_id), error)
            return 200, _envelope({
                "task": task,
                "interpretation": {
                    "implementation_status": "IMPLEMENTED",
                    "summary": understood["summary"],
                    "questions": understood["questions"],
                },
                "missing_information": understood["missing_information"],
                "next_action": understood["next_action"],
            })
        if path == "/api/agent/research":
            if set(body) != {"task_id", "expected_revision"}:
                raise WorkflowError("INVALID_REQUEST", "research 请求只接受 task_id 与 expected_revision。")
            task_id = _text(body.get("task_id", ""), "task_id", allow_empty=False)
            _require_task(body)
            started = REPOSITORY.begin_research(task_id, body.get("expected_revision"))
            product_query = started["product_query"]
            try:
                research = RESEARCH_SERVICE.retrieve_product_facts(product_query)
            except Exception:
                research = {
                    "status": "error", "query": product_query, "selected_product_model": None,
                    "candidate_models": [], "documents": [], "fact_records": [],
                    "knowledge_source": {
                        "mode": "local" if getattr(getattr(RESEARCH_SERVICE, "knowledge_service", None), "mode", "") == "local" else "ima",
                        "name": "任德耀新建华为PC知识库", "live": False,
                        "status": "unavailable", "message": "知识来源读取失败；未保存本次检索结果。",
                    },
                    "warnings": [], "missing_information": ["请检查知识来源配置后重试。"],
                    "next_action": "retry_research",
                    "error": {"code": "KNOWLEDGE_SOURCE_ERROR", "message": "知识来源读取失败；未保存本次检索结果。"},
                }
            if not isinstance(research, dict):
                research = {
                    "status": "error", "query": product_query, "selected_product_model": None,
                    "candidate_models": [], "documents": [], "fact_records": [],
                    "knowledge_source": {"mode": "ima", "name": "任德耀新建华为PC知识库", "live": False,
                                         "status": "unavailable", "message": "知识来源返回格式无效。"},
                    "warnings": [], "missing_information": [], "next_action": "retry_research",
                    "error": {"code": "INVALID_KNOWLEDGE_RESPONSE", "message": "知识来源返回格式无效。"},
                }

            fact_records = research.get("fact_records")
            if research.get("status") in {"success", "partial"} and isinstance(fact_records, list) and fact_records:
                completed = REPOSITORY.complete_research(
                    task_id, started["revision"], fact_records,
                    expected_product_query=product_query,
                    knowledge_source=research.get("knowledge_source"),
                    evidence_documents=getattr(research, "evidence_documents", []),
                )
                return 200, _envelope({
                    "task": completed,
                    "research": research,
                    "implementation_status": "IMPLEMENTED",
                    "next_action": research.get("next_action", "strategy_not_implemented"),
                })

            failed = REPOSITORY.fail_task(task_id, started["revision"])
            code = "KNOWLEDGE_SOURCE_ERROR"
            http_status = 502
            message = "知识检索未取得可保存的事实；未生成或保存事实。"
            if research.get("status") == "conflict":
                code, http_status, message = "PRODUCT_MODEL_CONFLICT", 409, "知识资料指向多个或不一致的产品型号；未保存事实。"
                conflict_error = research.get("error")
                if isinstance(conflict_error, dict) and conflict_error.get("code") == "SOURCE_CONFLICT":
                    code, message = "SOURCE_CONFLICT", "同一型号的资料参数存在冲突，请核对来源与配置条件。"
            elif research.get("status") == "needs_input":
                code, http_status, message = "PRODUCT_NEEDS_INPUT", 409, "当前产品型号无法唯一匹配知识资料；请补充精确型号。"
            elif research.get("status") == "partial":
                code, http_status, message = "NO_EXTRACTABLE_FACTS", 422, "已读取资料，但没有可安全保存的稳定产品事实。"
            elif research.get("status") == "error":
                error_data = research.get("error")
                if isinstance(error_data, dict) and isinstance(error_data.get("code"), str):
                    code = error_data["code"]
                source = research.get("knowledge_source")
                if isinstance(source, dict) and source.get("status") == "quota_limited":
                    code, message = "KNOWLEDGE_QUOTA_LIMITED", "ima 资料读取额度已达上限；本次检索未完成。"
                elif isinstance(source, dict) and source.get("status") == "unavailable":
                    message = "知识来源暂时不可用或请求超时；本次检索未完成。"
            return http_status, {
                "success": False,
                "data": {
                    "task": failed,
                    "research": research,
                    "recovery": "补充或核对产品型号，或在知识来源恢复后基于最新 task.revision 重试。",
                },
                "error": {"code": code, "message": message},
            }
        if path == "/api/strategy/generate":
            if set(body) != {"task_id", "expected_revision"}:
                raise WorkflowError("INVALID_REQUEST", "strategy/generate 请求字段不符合契约。")
            task_id = _text(body.get("task_id", ""), "task_id", allow_empty=False)
            task, context, eligible = REPOSITORY.strategy_snapshot(task_id, body.get("expected_revision"))
            service = STRATEGY_SERVICE if STRATEGY_SERVICE is not None else StrategyService(fact_checker=FACT_CHECKER)
            try:
                assessment = service.generate(task, eligible, context)
            except StrategyServiceError as error:
                REPOSITORY.strategy_snapshot(task_id, task["revision"])
                code = error.code
                status = 422 if code == "NO_VERIFIED_FACTS" else error.http_status
                return status, {"success": False, "data": {
                    "task": REPOSITORY.get(task_id), "implementation_status": "FAILED",
                    "next_action": "check_facts" if code == "NO_VERIFIED_FACTS" else "retry_strategy",
                    "diagnostics": _copy(error.diagnostics),
                }, "error": {"code": code, "message": error.message}}
            if not isinstance(assessment, dict) or assessment.get("status") != "passed":
                REPOSITORY.strategy_snapshot(task_id, task["revision"])
                details = assessment if isinstance(assessment, dict) else {}
                return 422, {"success": False, "data": {
                    "task": REPOSITORY.get(task_id), "attempts": details.get("attempts", 0),
                    "blocking_items": _copy(details.get("blocking_items", [])),
                    "fact_check": _copy(details.get("fact_check")),
                    "diagnostics": _copy(details.get("diagnostics", {})),
                    "next_action": "revise_strategy_or_research",
                }, "error": ({"code": "STRATEGY_RESPONSE_INVALID", "message": "策略结构或事实映射不符合契约；有限修正后仍无效，未保存策略。"}
                             if details.get("failure_type") == "response_schema" else
                             {"code": "STRATEGY_FACTS_UNSUPPORTED", "message": "策略包含未获当前来源支持的表达；已完成有限修正尝试，未保存或等待确认。"})}
            completed, strategy = REPOSITORY.add_strategy(
                task_id, task["revision"], assessment["draft"], assessment=assessment, context=context,
            )
            return 200, _envelope({
                "task": completed, "strategy": strategy, "fact_check": assessment["fact_check"],
                "attempts": assessment["attempts"], "implementation_status": "IMPLEMENTED",
                "diagnostics": _copy(assessment.get("diagnostics", {})),
                "next_action": "confirm_strategy",
            })
        if path == "/api/strategy/confirm":
            if set(body) != {"task_id", "expected_revision", "strategy_id", "strategy_version"}:
                raise WorkflowError("INVALID_REQUEST", "confirm 请求字段不符合契约。")
            task_id = _text(body.get("task_id", ""), "task_id", allow_empty=False)
            task, strategy = REPOSITORY.confirm_strategy(
                task_id, body.get("expected_revision"), body.get("strategy_id"), body.get("strategy_version"),
            )
            return 200, _envelope({"task": task, "strategy": strategy, "workflow_status": task["workflow_status"]})
        if path == "/api/strategy/handoff":
            if set(body) != {"task_id", "expected_revision", "strategy_id", "strategy_version"}:
                raise WorkflowError("INVALID_REQUEST", "handoff 请求必须绑定任务版本与策略 ID/版本。")
            task_id = _text(body.get("task_id", ""), "task_id", allow_empty=False)
            handoff = REPOSITORY.creative_handoff(
                task_id, body.get("expected_revision"), body.get("strategy_id"), body.get("strategy_version"),
            )
            return 200, _envelope({"handoff": handoff, "implementation_status": "IMPLEMENTED"})
        if path == "/api/facts/check":
            if set(body) != {"task_id", "expected_revision", "claims"}:
                raise WorkflowError("INVALID_REQUEST", "check 请求字段不符合契约。")
            task_id = _text(body.get("task_id", ""), "task_id", allow_empty=False)
            claims = body["claims"]
            if not isinstance(claims, list) or not claims or len(claims) > 100:
                raise WorkflowError("INVALID_REQUEST", "claims 必须是 1 至 100 项数组。")
            for claim in claims:
                if not isinstance(claim, dict) or set(claim) != {"claim", "fact_references"}:
                    raise WorkflowError("INVALID_REQUEST", "claims 项字段不符合契约。")
                _text(claim["claim"], "claim", allow_empty=False)
                refs = _list_of_text(claim["fact_references"], "fact_references")
                if len(refs) > 50 or len(refs) != len(set(refs)):
                    raise WorkflowError("INVALID_REQUEST", "fact_references 必须是至多 50 项且不重复的数组。")
            task, context = REPOSITORY.fact_check_snapshot(task_id, body["expected_revision"])
            # No repository lock is held across semantic model calls.
            try:
                assessment = FACT_CHECKER.check(task, _copy(claims), context)
            except Exception:
                # Still check the revision before reporting an external failure.
                REPOSITORY.fact_check_snapshot(task_id, task["revision"])
                return 502, {
                    "success": False,
                    "data": {"task": REPOSITORY.get(task_id), "recovery": "核查服务失败；已检索信息保留，请基于最新 revision 重试。"},
                    "error": {"code": "FACT_CHECK_FAILED", "message": "事实核查未完成；未采信任何异常输出。"},
                }
            completed, checked = REPOSITORY.complete_fact_check(task, context, claims, assessment)
            data = {"task": completed, "fact_check": checked,
                    "implementation_status": "IMPLEMENTED", "next_action": checked["next_action"]}
            if checked["errors"]:
                data["recovery"] = "部分语义核查未完成；证据与独立核查结果已保留，请使用最新 revision 重试待确认项。"
                return 502, {"success": False, "data": data, "error": checked["errors"][0]}
            return 200, _envelope(data)
        if path == "/api/facts/check-final":
            if set(body) != {"task_id", "expected_revision", "strategy_id", "strategy_version", "content"}:
                raise WorkflowError("INVALID_REQUEST", "check-final 请求字段不符合契约。")
            task_id = _text(body["task_id"], "task_id", allow_empty=False)
            content = validate_final_content(body["content"])
            task, context, strategy, eligible, binding = REPOSITORY.begin_final_check(
                task_id, body["expected_revision"], body["strategy_id"], body["strategy_version"], content,
            )
            service = FINAL_CHECK_SERVICE if FINAL_CHECK_SERVICE is not None else FinalCheckService(fact_checker=FACT_CHECKER)
            try:
                assessment = service.check(task, strategy, eligible, context, _copy(content))
            except Exception as error:
                current = REPOSITORY.assert_final_current(task, context, binding)
                return 502, {"success": False, "data": {
                    "task": current, "content_digest": binding["content_digest"], "content_version": binding["content_version"],
                    "diagnostics": _copy(error.diagnostics) if isinstance(error, FinalCheckError) else {},
                    "recovery": "成稿和已有策略未被改写；旧核查已失效，请基于最新 revision 修复服务后重新核查。",
                }, "error": {"code": error.code if isinstance(error, FinalCheckError) else "FINAL_CHECK_FAILED",
                             "message": error.message if isinstance(error, FinalCheckError) else "最终核查未完成；未授予通过状态。"}}
            completed, checked = REPOSITORY.complete_final_check(task, context, binding, content, assessment)
            data = {"task": completed, "final_check": checked, "implementation_status": "IMPLEMENTED",
                    "next_action": checked["next_action"]}
            if checked["errors"]:
                return 502, {"success": False, "data": data, "error": checked["errors"][0]}
            return 200, _envelope(data)
        raise WorkflowError("NOT_FOUND", "接口不存在。", http_status=404)
    except WorkflowError as error:
        return error.http_status, _error(error)
    except ContractValidationError as error:
        return 400, _error(WorkflowError("INVALID_CONTRACT", str(error)))
    except Exception:
        return 500, _error(WorkflowError("WORKFLOW_ERROR", "工作流暂时无法处理请求，请稍后重试。", http_status=500))
