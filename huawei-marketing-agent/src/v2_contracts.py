"""Typed request, task, strategy and fact-check contracts for workflow v2."""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, TypedDict


FieldName = Literal["product_query", "audience", "platform", "goal", "scene", "constraints"]
FieldStatus = Literal["unset", "confirmed", "cleared"]
ScenarioSource = Literal["user_input", "opportunity"]
ScenarioVerificationStatus = Literal["unverified"]
WorkflowStatus = Literal[
    "collecting_requirements", "researching", "ready_for_strategy",
    "awaiting_user_confirmation", "strategy_confirmed", "failed",
]
FactStatus = Literal["retrieved", "supported", "unsupported", "conflicting", "needs_confirmation", "stale"]
CheckStatus = Literal["supported", "unsupported", "conflicting", "needs_confirmation", "not_applicable"]

FIELD_NAMES = ("product_query", "audience", "platform", "goal", "scene", "constraints")
FIELD_STATUSES = ("unset", "confirmed", "cleared")
SCENARIO_CLEAR_FIELDS = (
    "scenario_inputs.time", "scenario_inputs.time.text",
    "scenario_inputs.store", "scenario_inputs.store.location_text",
    "scenario_inputs.store.nearby_landmarks",
    "scenario_inputs.usage", "scenario_inputs.usage.text",
)
CARD_FIELDS = {
    "scenario_inputs.time.text", "scenario_inputs.store.location_text",
    "scenario_inputs.store.nearby_landmarks", "scenario_inputs.usage.text",
}
QUESTION_FIELDS = set(FIELD_NAMES) | CARD_FIELDS
WORKFLOW_STATUSES = (
    "collecting_requirements", "researching", "ready_for_strategy",
    "awaiting_user_confirmation", "strategy_confirmed", "failed",
)
FACT_STATUSES = ("retrieved", "supported", "unsupported", "conflicting", "needs_confirmation", "stale")
CHECK_STATUSES = ("supported", "unsupported", "conflicting", "needs_confirmation", "not_applicable")
MAX_TEXT_LENGTH = 8000


class ConversationTurn(TypedDict):
    role: Literal["user", "assistant"]
    text: str
    at: str


class FieldStatuses(TypedDict):
    product_query: FieldStatus
    audience: FieldStatus
    platform: FieldStatus
    goal: FieldStatus
    scene: FieldStatus
    constraints: FieldStatus


class ScenarioTextInput(TypedDict):
    text: str
    field_status: FieldStatus
    source: ScenarioSource
    verification_status: ScenarioVerificationStatus


class ScenarioStoreInput(TypedDict):
    location_text: str
    location_status: FieldStatus
    nearby_landmarks: List[str]
    nearby_landmarks_status: FieldStatus
    source: ScenarioSource
    verification_status: ScenarioVerificationStatus


class ScenarioInputs(TypedDict):
    time: ScenarioTextInput
    store: ScenarioStoreInput
    usage: ScenarioTextInput


class QuestionCardOption(TypedDict):
    option_id: str
    label: str


class QuestionCard(TypedDict):
    question_id: str
    issued_revision: int
    field: str
    prompt: str
    mode: Literal["single", "multiple"]
    options: List[QuestionCardOption]
    allow_free_text: bool


class CardAnswer(TypedDict):
    question_id: str
    option_ids: List[str]


class FactRecord(TypedDict):
    """A retrieved claim with provenance; model confidence is deliberately absent."""

    fact_id: str
    product_model: str
    claim: str
    evidence_text: str
    source_ref: str
    source_type: Literal["official", "trusted_third_party", "other", "unknown"]
    retrieved_at: str
    valid_until: Optional[str]
    status: FactStatus


class OutlineSection(TypedDict):
    section: str
    purpose: str
    fact_references: List[str]


class AudienceContext(TypedDict):
    description: str
    basis: str
    basis_type: Literal["user_provided", "known", "inference", "unconfirmed"]


class StrategyDraft(TypedDict):
    """Strategy content returned by a strategy implementation, without server metadata."""

    task_summary: str
    topic: str
    audience: AudienceContext
    audience_need: str
    core_message: str
    content_angle: str
    content_format: str
    content_outline: List[OutlineSection]
    cta: str
    fact_references: List[str]
    assumptions: List[str]
    pending_confirmations: List[str]
    risk_notes: List[str]


class Strategy(StrategyDraft):
    strategy_id: str
    task_id: str
    task_revision: int
    strategy_version: int
    confirmation_status: Literal["pending", "confirmed", "superseded"]
    confirmed_at_task_revision: Optional[int]


class FactCheckBinding(TypedDict, total=False):
    # Additive binding for v2 checks; older serialized examples remain readable.
    fact_references: List[str]


class FactCheckResult(FactCheckBinding):
    task_id: str
    task_revision: int
    claim: str
    status: CheckStatus
    evidence: List[str]
    source_refs: List[str]
    reason: str
    suggested_action: Literal["retain", "rewrite", "remove", "confirm", "none"]


class TaskContext(TypedDict):
    """Task snapshot separating immutable input, conversation and current effective fields."""

    task_id: str
    revision: int
    source: Literal["direct", "opportunity"]
    user_input: str
    conversation: List[ConversationTurn]
    product_query: str
    audience: str
    platform: str
    goal: str
    scene: str
    constraints: List[str]
    scenario_inputs: ScenarioInputs
    field_status: FieldStatuses
    question_cards: List[QuestionCard]
    excluded_scenes: List[str]
    opportunity_context: Optional[Dict[str, Any]]
    fact_records: List[FactRecord]
    current_strategy_id: Optional[str]
    current_strategy_version: Optional[int]
    workflow_status: WorkflowStatus


class ContractValidationError(ValueError):
    """Raised when a Python value does not satisfy a v2 runtime contract."""


def _string(value: Any, name: str, allow_empty: bool = False, max_length: int = MAX_TEXT_LENGTH) -> str:
    if not isinstance(value, str) or len(value) > max_length or (not allow_empty and not value.strip()):
        raise ContractValidationError(f"{name} 必须是长度不超过 {max_length} 的文本。")
    return value


def _string_list(value: Any, name: str, allow_empty_items: bool = False) -> List[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or len(item) > MAX_TEXT_LENGTH or (not allow_empty_items and not item.strip())
        for item in value
    ):
        raise ContractValidationError(f"{name} 必须是文本数组。")
    return value


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ContractValidationError(f"{name} 必须是正整数。")
    return value


def _iso_datetime(value: Any, name: str, optional: bool = False) -> Optional[str]:
    if optional and value is None:
        return None
    text = _string(value, name, max_length=64)
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractValidationError(f"{name} 必须是 ISO 8601 时间。") from exc
    return text


def _json_value(value: Any, name: str, depth: int = 0) -> None:
    if depth > 12:
        raise ContractValidationError(f"{name} 嵌套层级过深。")
    if value is None or isinstance(value, (str, bool, int)):
        if isinstance(value, str) and len(value) > MAX_TEXT_LENGTH:
            raise ContractValidationError(f"{name} 中的文本过长。")
        return
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ContractValidationError(f"{name} 包含无效数值。")
        return
    if isinstance(value, list):
        if len(value) > 500:
            raise ContractValidationError(f"{name} 项数过多。")
        for item in value:
            _json_value(item, name, depth + 1)
        return
    if isinstance(value, dict):
        if len(value) > 200 or any(not isinstance(key, str) for key in value):
            raise ContractValidationError(f"{name} 对象结构无效。")
        for item in value.values():
            _json_value(item, name, depth + 1)
        return
    raise ContractValidationError(f"{name} 必须是 JSON 兼容数据。")


def validate_fact_record(value: Any) -> FactRecord:
    if not isinstance(value, dict):
        raise ContractValidationError("FactRecord 必须是对象。")
    required = {
        "fact_id", "product_model", "claim", "evidence_text", "source_ref", "source_type",
        "retrieved_at", "valid_until", "status",
    }
    if set(value) != required:
        raise ContractValidationError("FactRecord 字段不符合契约。")
    record = dict(value)
    _string(record["fact_id"], "fact_id", max_length=120)
    _string(record["product_model"], "product_model")
    _string(record["claim"], "claim")
    _string(record["evidence_text"], "evidence_text", allow_empty=True)
    _string(record["source_ref"], "source_ref", allow_empty=True, max_length=1000)
    if record["source_type"] not in ("official", "trusted_third_party", "other", "unknown"):
        raise ContractValidationError("source_type 不符合枚举值。")
    _iso_datetime(record["retrieved_at"], "retrieved_at")
    _iso_datetime(record["valid_until"], "valid_until", optional=True)
    if record["status"] not in FACT_STATUSES:
        raise ContractValidationError("FactRecord status 不符合枚举值。")
    if record["status"] in {"retrieved", "supported"} and (not record["evidence_text"].strip() or not record["source_ref"].strip()):
        raise ContractValidationError("已检索或支持的事实必须带原文和来源。")
    return record  # type: ignore[return-value]


def validate_task_context(value: Any) -> TaskContext:
    if not isinstance(value, dict):
        raise ContractValidationError("TaskContext 必须是对象。")
    required = {
        "task_id", "revision", "source", "user_input", "conversation", "product_query", "audience",
        "platform", "goal", "scene", "constraints", "field_status", "excluded_scenes",
        "opportunity_context", "fact_records", "current_strategy_id", "current_strategy_version", "workflow_status",
    }
    optional = {"scenario_inputs", "question_cards"}
    if not required <= set(value) or set(value) - required - optional:
        raise ContractValidationError("TaskContext 字段不符合契约。")
    task = dict(value)
    task.setdefault("scenario_inputs", {
        "time": {"text": "", "field_status": "unset", "source": "user_input", "verification_status": "unverified"},
        "store": {"location_text": "", "location_status": "unset", "nearby_landmarks": [],
                  "nearby_landmarks_status": "unset", "source": "user_input", "verification_status": "unverified",
                  },
        "usage": {"text": "", "field_status": "unset", "source": "user_input", "verification_status": "unverified"},
    })
    task.setdefault("question_cards", [])
    _string(task["task_id"], "task_id", max_length=120)
    _positive_int(task["revision"], "revision")
    if task["source"] not in {"direct", "opportunity"}:
        raise ContractValidationError("source 不符合枚举值。")
    _string(task["user_input"], "user_input", allow_empty=True)
    for name in ("product_query", "audience", "platform", "goal", "scene"):
        _string(task[name], name, allow_empty=True)
    _string_list(task["constraints"], "constraints")
    _string_list(task["excluded_scenes"], "excluded_scenes")
    scenario = task["scenario_inputs"]
    if not isinstance(scenario, dict) or set(scenario) != {"time", "store", "usage"}:
        raise ContractValidationError("scenario_inputs 必须包含 time、store 和 usage。")
    for name in ("time", "usage"):
        item = scenario[name]
        if not isinstance(item, dict) or set(item) != {"text", "field_status", "source", "verification_status"}:
            raise ContractValidationError(f"scenario_inputs.{name} 字段无效。")
        _string(item["text"], f"scenario_inputs.{name}.text", allow_empty=True, max_length=2000)
        if item["field_status"] not in FIELD_STATUSES:
            raise ContractValidationError(f"scenario_inputs.{name}.field_status 无效。")
        if (item["field_status"] == "confirmed") != bool(item["text"]):
            raise ContractValidationError(f"scenario_inputs.{name}.field_status 与值不一致。")
        if item["source"] not in {"user_input", "opportunity"} or item["verification_status"] != "unverified":
            raise ContractValidationError(f"scenario_inputs.{name} 来源或核验状态无效。")
    store = scenario["store"]
    if not isinstance(store, dict):
        raise ContractValidationError("scenario_inputs.store 字段无效。")
    # Additive defaults keep earlier v2 snapshots and fixtures readable.
    if set(store) != {"location_text", "location_status", "nearby_landmarks", "nearby_landmarks_status", "source", "verification_status"}:
        raise ContractValidationError("scenario_inputs.store 字段无效。")
    _string(store["location_text"], "scenario_inputs.store.location_text", allow_empty=True, max_length=1000)
    _string_list(store["nearby_landmarks"], "scenario_inputs.store.nearby_landmarks")
    if len(store["nearby_landmarks"]) > 20 or any(len(item) > 200 for item in store["nearby_landmarks"]):
        raise ContractValidationError("附近地标数量或长度超出限制。")
    for status_name, value in (("location_status", store["location_text"]),
                               ("nearby_landmarks_status", store["nearby_landmarks"])):
        if store[status_name] not in FIELD_STATUSES or (store[status_name] == "confirmed") != bool(value):
            raise ContractValidationError(f"scenario_inputs.store.{status_name} 与值不一致。")
    if store["source"] not in {"user_input", "opportunity"} or store["verification_status"] != "unverified":
        raise ContractValidationError("scenario_inputs.store 来源或核验状态无效。")
    statuses = task["field_status"]
    if not isinstance(statuses, dict) or set(statuses) != set(FIELD_NAMES):
        raise ContractValidationError("field_status 必须逐项覆盖当前可编辑字段。")
    values = {**{name: task[name] for name in FIELD_NAMES if name != "constraints"},
              "constraints": task["constraints"]}
    for name, status in statuses.items():
        if status not in FIELD_STATUSES:
            raise ContractValidationError(f"field_status.{name} 不符合枚举值。")
        has_value = bool(values[name])
        if (status == "confirmed") != has_value:
            raise ContractValidationError(f"field_status.{name} 与当前有效值不一致。")
    cards = task["question_cards"]
    if not isinstance(cards, list) or len(cards) > 1:
        raise ContractValidationError("question_cards 每轮最多包含一张卡片。")
    card_ids = set()
    for card in cards:
        if not isinstance(card, dict) or set(card) != {
            "question_id", "issued_revision", "field", "prompt", "mode", "options", "allow_free_text",
        }:
            raise ContractValidationError("question_cards 项字段无效。")
        _string(card["question_id"], "question_id", max_length=120)
        _positive_int(card["issued_revision"], "issued_revision")
        if card["issued_revision"] != task["revision"]:
            raise ContractValidationError("question_cards 必须绑定当前任务版本。")
        if card["field"] not in CARD_FIELDS:
            raise ContractValidationError("question_cards.field 不受支持。")
        _string(card["prompt"], "question_cards.prompt", max_length=500)
        if card["mode"] not in {"single", "multiple"} or not isinstance(card["allow_free_text"], bool):
            raise ContractValidationError("question_cards 选择模式或自由输入标记无效。")
        options = card["options"]
        if not isinstance(options, list) or not options or len(options) > 20:
            raise ContractValidationError("question_cards.options 必须包含 1 至 20 项。")
        option_ids = set()
        for option in options:
            if not isinstance(option, dict) or set(option) != {"option_id", "label"}:
                raise ContractValidationError("question_cards.option 字段无效。")
            _string(option["option_id"], "option_id", max_length=120)
            _string(option["label"], "option.label", max_length=200)
            if option["option_id"] in option_ids:
                raise ContractValidationError("question_cards.option_id 不能重复。")
            option_ids.add(option["option_id"])
        if card["question_id"] in card_ids:
            raise ContractValidationError("question_cards.question_id 不能重复。")
        card_ids.add(card["question_id"])
    turns = task["conversation"]
    if not isinstance(turns, list) or len(turns) > 500:
        raise ContractValidationError("conversation 必须是有限长度的数组。")
    for turn in turns:
        if not isinstance(turn, dict) or set(turn) != {"role", "text", "at"}:
            raise ContractValidationError("conversation 记录字段无效。")
        if turn["role"] not in {"user", "assistant"}:
            raise ContractValidationError("conversation.role 不符合枚举值。")
        _string(turn["text"], "conversation.text", allow_empty=True)
        _iso_datetime(turn["at"], "conversation.at")
    opportunity = task["opportunity_context"]
    if opportunity is not None:
        if not isinstance(opportunity, dict):
            raise ContractValidationError("opportunity_context 必须是对象或 null。")
        _json_value(opportunity, "opportunity_context")
    if task["source"] == "opportunity" and not opportunity:
        raise ContractValidationError("机会来源任务必须提供 opportunity_context。")
    facts = task["fact_records"]
    if not isinstance(facts, list) or len(facts) > 500:
        raise ContractValidationError("fact_records 必须是有限长度的数组。")
    ids = set()
    for fact in facts:
        validated = validate_fact_record(fact)
        if validated["fact_id"] in ids:
            raise ContractValidationError("fact_records.fact_id 不能重复。")
        ids.add(validated["fact_id"])
    if len({fact["product_model"] for fact in facts}) > 1:
        raise ContractValidationError("单个 TaskContext 不能混合多个精确产品型号的事实。")
    if task["current_strategy_id"] is not None:
        _string(task["current_strategy_id"], "current_strategy_id", max_length=120)
    if task["current_strategy_version"] is not None:
        _positive_int(task["current_strategy_version"], "current_strategy_version")
    if (task["current_strategy_id"] is None) != (task["current_strategy_version"] is None):
        raise ContractValidationError("当前策略 ID 与版本必须同时存在或为空。")
    if task["workflow_status"] not in WORKFLOW_STATUSES:
        raise ContractValidationError("workflow_status 不符合枚举值。")
    if task["workflow_status"] in {"awaiting_user_confirmation", "strategy_confirmed"} and task["current_strategy_id"] is None:
        raise ContractValidationError("等待或完成策略确认的任务必须绑定当前策略。")
    if task["workflow_status"] in {"collecting_requirements", "researching", "ready_for_strategy"} and task["current_strategy_id"] is not None:
        raise ContractValidationError("策略生成前的任务不能绑定当前策略。")
    return task  # type: ignore[return-value]


STRATEGY_DRAFT_FIELDS = {
    "task_summary", "topic", "audience", "audience_need", "core_message", "content_angle",
    "content_format", "content_outline", "cta", "fact_references", "assumptions",
    "pending_confirmations", "risk_notes",
}


def validate_strategy_draft(value: Any, known_fact_ids: Optional[set] = None) -> StrategyDraft:
    if not isinstance(value, dict) or set(value) != STRATEGY_DRAFT_FIELDS:
        raise ContractValidationError("StrategyDraft 字段不符合契约。")
    draft = dict(value)
    for name in ("task_summary", "topic", "audience_need", "core_message", "content_angle", "content_format"):
        _string(draft[name], name)
    audience = draft["audience"]
    if not isinstance(audience, dict) or set(audience) != {"description", "basis", "basis_type"}:
        raise ContractValidationError("strategy.audience 字段不符合契约。")
    _string(audience["description"], "audience.description")
    _string(audience["basis"], "audience.basis", allow_empty=True)
    if audience["basis_type"] not in {"user_provided", "known", "inference", "unconfirmed"}:
        raise ContractValidationError("audience.basis_type 不符合枚举值。")
    outline = draft["content_outline"]
    if not isinstance(outline, list) or not outline:
        raise ContractValidationError("content_outline 必须至少包含一节。")
    for item in outline:
        if not isinstance(item, dict) or set(item) != {"section", "purpose", "fact_references"}:
            raise ContractValidationError("content_outline 项字段无效。")
        _string(item["section"], "content_outline.section")
        _string(item["purpose"], "content_outline.purpose", allow_empty=True)
        outline_refs = _string_list(item["fact_references"], "content_outline.fact_references")
        if known_fact_ids is not None and any(ref not in known_fact_ids for ref in outline_refs):
            raise ContractValidationError("content_outline.fact_references 必须指向当前任务中的 FactRecord。")
    _string(draft["cta"], "cta", allow_empty=True)
    references = _string_list(draft["fact_references"], "fact_references")
    if len(references) != len(set(references)):
        raise ContractValidationError("fact_references 不能重复。")
    if known_fact_ids is not None and any(ref not in known_fact_ids for ref in references):
        raise ContractValidationError("fact_references 必须指向当前任务中的 FactRecord。")
    for name in ("assumptions", "pending_confirmations", "risk_notes"):
        _string_list(draft[name], name)
    return draft  # type: ignore[return-value]


def validate_strategy(value: Any, known_fact_ids: Optional[set] = None) -> Strategy:
    if not isinstance(value, dict) or set(value) != STRATEGY_DRAFT_FIELDS | {
        "strategy_id", "task_id", "task_revision", "strategy_version", "confirmation_status",
        "confirmed_at_task_revision",
    }:
        raise ContractValidationError("Strategy 字段不符合契约。")
    draft = {key: value[key] for key in STRATEGY_DRAFT_FIELDS}
    validate_strategy_draft(draft, known_fact_ids)
    _string(value["strategy_id"], "strategy_id", max_length=120)
    _string(value["task_id"], "task_id", max_length=120)
    _positive_int(value["task_revision"], "task_revision")
    _positive_int(value["strategy_version"], "strategy_version")
    if value["confirmation_status"] not in {"pending", "confirmed", "superseded"}:
        raise ContractValidationError("confirmation_status 不符合枚举值。")
    confirmed_revision = value["confirmed_at_task_revision"]
    if confirmed_revision is not None:
        _positive_int(confirmed_revision, "confirmed_at_task_revision")
    if (value["confirmation_status"] == "confirmed") != (confirmed_revision is not None):
        raise ContractValidationError("策略确认状态与确认版本不一致。")
    return dict(value)  # type: ignore[return-value]


def validate_fact_check_result(value: Any) -> FactCheckResult:
    required = {"task_id", "task_revision", "claim", "status", "evidence", "source_refs", "reason", "suggested_action"}
    if not isinstance(value, dict) or not required <= set(value) or set(value) - required - {"fact_references"}:
        raise ContractValidationError("FactCheckResult 字段不符合契约。")
    _string(value["task_id"], "task_id", max_length=120)
    _positive_int(value["task_revision"], "task_revision")
    _string(value["claim"], "claim")
    if value["status"] not in CHECK_STATUSES:
        raise ContractValidationError("FactCheckResult.status 不符合枚举值。")
    _string_list(value["evidence"], "evidence")
    _string_list(value["source_refs"], "source_refs")
    if "fact_references" in value:
        references = _string_list(value["fact_references"], "fact_references")
        if len(references) != len(set(references)):
            raise ContractValidationError("fact_references 不能重复。")
    _string(value["reason"], "reason", allow_empty=True)
    if value["suggested_action"] not in {"retain", "rewrite", "remove", "confirm", "none"}:
        raise ContractValidationError("suggested_action 不符合枚举值。")
    if value["status"] == "supported" and (not value["evidence"] or not value["source_refs"]):
        raise ContractValidationError("supported 结果必须有证据和来源。")
    return dict(value)  # type: ignore[return-value]
