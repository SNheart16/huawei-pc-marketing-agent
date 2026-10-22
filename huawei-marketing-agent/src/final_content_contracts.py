"""Additive final-content contracts; legacy /api/run and TaskContext stay intact."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, List, TypedDict

from .v2_contracts import ContractValidationError, MAX_TEXT_LENGTH, FactCheckResult


class FinalContentOptions(TypedDict, total=False):
    selling_points: List[str]
    tags: List[str]
    additional_text: List[str]
    fact_references: List[str]


class FinalContent(FinalContentOptions):
    title: str
    body: str
    cta: str
    plain_text: str
    images: List[dict]


class FinalTextItem(TypedDict):
    field_path: str
    check: FactCheckResult


REQUIRED_CONTENT = {"title", "body", "cta", "plain_text", "images"}
OPTIONAL_CONTENT = {"selling_points", "tags", "additional_text", "fact_references"}
IMAGE_TEXT_FIELDS = ("name", "caption", "description", "alt", "text", "product_model", "source")
IMAGE_FIELDS = set(IMAGE_TEXT_FIELDS) | {"url", "source", "source_ref", "status", "fact_references"}


def _text(value: Any) -> bool:
    return isinstance(value, str) and len(value) <= MAX_TEXT_LENGTH


def _refs(value: Any) -> bool:
    return (isinstance(value, list) and len(value) <= 50
            and all(isinstance(item, str) and 0 < len(item) <= 200 for item in value)
            and len(value) == len(set(value)))


def validate_final_content(value: Any) -> FinalContent:
    if (not isinstance(value, dict) or not REQUIRED_CONTENT <= set(value)
            or set(value) - REQUIRED_CONTENT - OPTIONAL_CONTENT):
        raise ContractValidationError("content 必须包含既定五个字段；只允许文档声明的附加文字和引用字段。")
    if any(not _text(value[key]) for key in ("title", "body", "cta", "plain_text")):
        raise ContractValidationError("成稿文字必须是有限长度文本。")
    if not any(value[key].strip() for key in ("title", "body", "cta", "plain_text")):
        raise ContractValidationError("最终核查需要非空成稿文字。")
    for key in ("selling_points", "tags", "additional_text"):
        items = value.get(key, [])
        if not isinstance(items, list) or len(items) > 50 or any(not _text(item) for item in items):
            raise ContractValidationError("附加展示文字必须是有限长度文本数组。")
    if not _refs(value.get("fact_references", [])):
        raise ContractValidationError("成稿引用必须是不重复的有限 fact ID 数组。")
    images = value["images"]
    if not isinstance(images, list) or len(images) > 20:
        raise ContractValidationError("content.images 必须是至多 20 项数组。")
    for image in images:
        if not isinstance(image, dict) or set(image) - IMAGE_FIELDS:
            raise ContractValidationError("图片项包含未声明字段；所有展示文字必须放在明确的图片文字字段中。")
        if any(not _text(image[key]) for key in image if key not in {"url", "status", "fact_references"}):
            raise ContractValidationError("图片说明和来源必须是有限长度文本。")
        if image.get("url") is not None and not _text(image["url"]):
            raise ContractValidationError("图片 URL 只能为文本或 null；本接口不获取图片。")
        if "status" in image and (not isinstance(image["status"], str) or image["status"] not in {"unknown", "confirmed", "unmatched"}):
            raise ContractValidationError("图片声明状态无效。")
        if not _refs(image.get("fact_references", [])):
            raise ContractValidationError("图片引用必须是有限 fact ID 数组。")
    if len(json.dumps(value, ensure_ascii=False)) > 100000:
        raise ContractValidationError("成稿超过最终核查允许的总长度。")
    return copy.deepcopy(value)


def content_digest(content: dict) -> str:
    """Exact JSON-content binding, including every displayed string and image ref."""
    encoded = json.dumps(content, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def content_texts(content: dict) -> list:
    fields = [(key, content[key]) for key in ("title", "body", "cta", "plain_text")]
    for key in ("selling_points", "tags", "additional_text"):
        fields.extend((f"{key}[{index}]", text) for index, text in enumerate(content.get(key, [])))
    for index, image in enumerate(content["images"]):
        fields.extend((f"images[{index}].{key}", image[key]) for key in IMAGE_TEXT_FIELDS if key in image)
    return [(path, text) for path, text in fields if text.strip()]
