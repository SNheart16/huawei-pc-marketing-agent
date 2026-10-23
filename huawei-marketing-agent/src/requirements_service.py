"""LLM-backed interpretation of user requirements, without product retrieval."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

from .llm_client import LLMClient, LLMClientError
from .v2_contracts import CARD_FIELDS, FIELD_NAMES, MAX_TEXT_LENGTH, SCENARIO_CLEAR_FIELDS


class RequirementsError(RuntimeError):
    def __init__(self, code: str, message: str, http_status: int = 502) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def _prompt_path() -> Path:
    configured = os.environ.get("AGENT_UNDERSTANDING_PROMPT_PATH")
    if configured and configured.strip():
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[2] / "prompts" / "understanding-system.md"


def _safe_task_context(task: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "source": task["source"],
        "user_input": task["user_input"],
        "conversation": task["conversation"][-20:],
        "product_query": task["product_query"],
        "audience": task["audience"],
        "platform": task["platform"],
        "goal": task["goal"],
        "scene": task["scene"],
        "constraints": task["constraints"],
        "scenario_inputs": task["scenario_inputs"],
        "field_status": task["field_status"],
        "excluded_scenes": task["excluded_scenes"],
        "opportunity_context": task["opportunity_context"],
    }


def _normalize_result(value: Any) -> Dict[str, Any]:
    required = {"summary", "updates", "clear_fields", "excluded_scenes", "question"}
    optional = {"scenario_updates", "question_card"}
    if not isinstance(value, dict) or not required <= set(value) or set(value) - required - optional:
        raise RequirementsError("INVALID_MODEL_RESPONSE", "需求理解结果结构不符合服务端契约。")

    summary = value["summary"]
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 500:
        raise RequirementsError("INVALID_MODEL_RESPONSE", "需求摘要为空或超出允许长度。")

    updates = value["updates"]
    if not isinstance(updates, dict) or set(updates) - set(FIELD_NAMES):
        raise RequirementsError("INVALID_MODEL_RESPONSE", "需求字段更新包含不支持的字段。")
    normalized_updates: Dict[str, Any] = {}
    for field, item in updates.items():
        if field == "constraints":
            if (not isinstance(item, list) or not item or len(item) > 100
                    or any(not isinstance(entry, str) or not entry.strip() or len(entry) > MAX_TEXT_LENGTH for entry in item)):
                raise RequirementsError("INVALID_MODEL_RESPONSE", "限制条件更新必须是有效的文本数组。")
            normalized_updates[field] = list(dict.fromkeys(item))
        elif not isinstance(item, str) or not item.strip() or len(item) > MAX_TEXT_LENGTH:
            raise RequirementsError("INVALID_MODEL_RESPONSE", f"{field} 更新必须是非空文本。")
        else:
            normalized_updates[field] = item.strip()

    clears = value["clear_fields"]
    allowed_clears = set(FIELD_NAMES) | set(SCENARIO_CLEAR_FIELDS)
    if (not isinstance(clears, list) or len(clears) > len(allowed_clears)
            or any(not isinstance(field, str) or field not in allowed_clears for field in clears)
            or len(set(clears)) != len(clears)):
        raise RequirementsError("INVALID_MODEL_RESPONSE", "清空字段列表无效。")
    if set(clears) & set(normalized_updates):
        raise RequirementsError("INVALID_MODEL_RESPONSE", "同一字段不能同时更新和清空。")

    excluded = value["excluded_scenes"]
    if (not isinstance(excluded, list) or len(excluded) > 100
            or any(not isinstance(item, str) or not item.strip() or len(item) > MAX_TEXT_LENGTH for item in excluded)):
        raise RequirementsError("INVALID_MODEL_RESPONSE", "排除场景必须是有效的文本数组。")

    question = value["question"]
    if question is not None and (not isinstance(question, str) or not question.strip() or len(question) > 500):
        raise RequirementsError("INVALID_MODEL_RESPONSE", "核心追问必须是非空文本或 null。")

    scenario_updates = value.get("scenario_updates", {})
    if not isinstance(scenario_updates, dict) or set(scenario_updates) - {"time", "store", "usage"}:
        raise RequirementsError("INVALID_MODEL_RESPONSE", "场景字段更新包含不支持的字段。")
    normalized_scenario: Dict[str, Any] = {}
    allowed_scenario_fields = {
        "time": {"text"}, "store": {"location_text", "nearby_landmarks"}, "usage": {"text"},
    }
    for group, fields in scenario_updates.items():
        item = scenario_updates[group]
        if not isinstance(item, dict) or set(item) - allowed_scenario_fields[group] or not item:
            raise RequirementsError("INVALID_MODEL_RESPONSE", f"scenario_updates.{group} 结构无效。")
        normalized_scenario[group] = {}
        for name, entry in item.items():
            if name == "nearby_landmarks":
                if (not isinstance(entry, list) or not entry or len(entry) > 20
                        or any(not isinstance(text, str) or not text.strip() or len(text) > 200 for text in entry)):
                    raise RequirementsError("INVALID_MODEL_RESPONSE", "nearby_landmarks 必须是 1 至 20 项有效文本。")
                normalized_scenario[group][name] = list(dict.fromkeys(text.strip() for text in entry))
            elif not isinstance(entry, str) or not entry.strip() or len(entry) > (1000 if group == "store" else 2000):
                raise RequirementsError("INVALID_MODEL_RESPONSE", f"scenario_updates.{group}.{name} 必须是有效文本。")
            else:
                normalized_scenario[group][name] = entry.strip()

    question_card = value.get("question_card")
    if question_card is not None and question is None:
        raise RequirementsError("INVALID_MODEL_RESPONSE", "问题卡片必须与唯一追问同时提供。")
    if question_card is not None:
        if not isinstance(question_card, dict) or set(question_card) != {"field", "mode", "options", "allow_free_text"}:
            raise RequirementsError("INVALID_MODEL_RESPONSE", "问题卡片结构无效。")
        if question_card["field"] not in CARD_FIELDS:
            raise RequirementsError("INVALID_MODEL_RESPONSE", "问题卡片只能询问结构化场景字段。")
        if question_card["mode"] not in {"single", "multiple"} or not isinstance(question_card["allow_free_text"], bool):
            raise RequirementsError("INVALID_MODEL_RESPONSE", "问题卡片的选择模式或自由输入标记无效。")
        options = question_card["options"]
        if (not isinstance(options, list) or not options or len(options) > 20
                or any(not isinstance(label, str) or not label.strip() or len(label) > 200 for label in options)
                or len({label.strip() for label in options}) != len(options)):
            raise RequirementsError("INVALID_MODEL_RESPONSE", "问题卡片选项必须是 1 至 20 项不重复文本。")
        question_card = {"field": question_card["field"], "mode": question_card["mode"],
                         "options": [label.strip() for label in options],
                         "allow_free_text": question_card["allow_free_text"]}

    return {
        "summary": summary.strip(),
        "updates": normalized_updates,
        "clear_fields": list(clears),
        "excluded_scenes": list(dict.fromkeys(item.strip() for item in excluded)),
        "question": question.strip() if isinstance(question, str) else None,
        "scenario_updates": normalized_scenario,
        "question_card": question_card,
    }


def interpret_requirements(
    task: Dict[str, Any],
    current_turn: str,
    explicit_updates: Optional[Dict[str, Any]] = None,
    explicit_clear_fields: Optional[list] = None,
    explicit_scenario_updates: Optional[Dict[str, Any]] = None,
    card_answers: Optional[list] = None,
) -> Dict[str, Any]:
    """Call the configured LLM and validate its field-update suggestions."""
    prompt_path = _prompt_path()
    try:
        prompt = prompt_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError, ValueError):
        raise RequirementsError(
            "UNDERSTANDING_PROMPT_UNAVAILABLE",
            "需求理解提示词不可用；任务信息已保存，请检查项目提示词配置后重试。",
            500,
        ) from None
    if not prompt.strip():
        raise RequirementsError(
            "UNDERSTANDING_PROMPT_UNAVAILABLE",
            "需求理解提示词为空；任务信息已保存，请补齐提示词后重试。",
            500,
        )

    payload = {
        "task": _safe_task_context(task),
        "current_turn": current_turn,
        "explicit_updates": explicit_updates or {},
        "explicit_clear_fields": explicit_clear_fields or [],
        "explicit_scenario_updates": explicit_scenario_updates or {},
        "card_answers": card_answers or [],
    }
    try:
        result = LLMClient(timeout=60).generate_json(prompt, payload)
    except LLMClientError:
        raise RequirementsError(
            "LLM_UNAVAILABLE",
            "需求理解模型调用失败；任务信息已保存，请检查模型配置或稍后使用最新 revision 重试。",
            502,
        ) from None
    except (TypeError, ValueError):
        raise RequirementsError(
            "INVALID_MODEL_RESPONSE",
            "需求理解模型未返回可解析的 JSON；任务信息已保存，请基于最新 revision 重试。",
            502,
        ) from None
    return _normalize_result(result)
