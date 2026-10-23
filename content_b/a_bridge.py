"""Same-process bridge: server-owned A handoff, unchanged A final-check API."""
from copy import deepcopy
from .contracts import ContentError


def _workflow():
    from src import workflow_service
    return workflow_service


def _handoff(binding, current=False):
    workflow = _workflow()
    try:
        revision = workflow.REPOSITORY.get(binding["task_id"])["revision"] if current else binding["expected_revision"]
        return workflow.REPOSITORY.creative_handoff(binding["task_id"], revision, binding["strategy_id"], binding["strategy_version"])
    except workflow.WorkflowError as error:
        raise ContentError(error.code, error.message, error.http_status) from None


def assert_current(binding):
    """Check the same confirmed strategy before spending on a regeneration."""
    return _handoff(binding, current=True)


def from_handoff(payload):
    required = {"task_id", "expected_revision", "strategy_id", "strategy_version"}
    optional = {"copy_mode", "image_mode", "image_count", "art_direction", "idempotency_key", "reference_id"}
    if not isinstance(payload, dict) or not required <= set(payload) or set(payload) - required - optional:
        raise ContentError("INVALID_INPUT", "请提供当前任务及已确认策略的实际版本绑定。")
    binding = {key: payload[key] for key in required}
    handoff = _handoff(binding)
    strategy = deepcopy(handoff["strategy"])
    audience = strategy["audience"]
    strategy["audience"] = audience["description"] if isinstance(audience, dict) else audience
    strategy["content_outline"] = [": ".join(part for part in (item.get("section", ""), item.get("purpose", "")) if part) if isinstance(item, dict) else item for item in strategy["content_outline"]]
    strategy.update(tone="真实克制", constraints="；".join(handoff["user_constraints"]), avoid=[])
    facts = []
    # A's handoff gate, not the retrieved label, grants current eligibility.
    for record in handoff["fact_records"]:
        fact = deepcopy(record)
        fact["status"] = "supported"
        fact["valid_until"] = fact.get("valid_until") or ""
        facts.append(fact)
    return {**{key: deepcopy(payload[key]) for key in optional if key in payload},
        "task_id": handoff["task"]["task_id"], "confirmed": True,
        "platform": handoff["task"]["platform"], "strategy": strategy,
        "product_context": {"model": handoff["task"]["product_query"], "facts": facts},
        "a_binding": binding, "knowledge_source": deepcopy(handoff["knowledge_source"]),
        "source_limits": deepcopy(handoff["source_limits"]),
        "scenario_inputs": deepcopy(handoff["task"].get("scenario_inputs", {}))}


def final_content(payload):
    copy = payload["copy"]
    # B's asset provenance is retained in B, never forged into A's evidence refs.
    images = [{"name": image.get("role") or image.get("image_id", ""),
        "alt": image.get("alt", ""), "caption": "\n".join(image.get("text_content", [])),
        "product_model": image.get("product_model", ""), "url": image.get("url"),
        "status": "unknown"} for image in payload["images"]]
    return {"title": copy["title"], "body": copy["body"], "cta": copy["cta"],
        "plain_text": "\n\n".join(part for part in (copy["title"], copy["body"], copy["cta"], " ".join(copy.get("hashtags", []))) if part),
        "tags": deepcopy(copy.get("hashtags", [])), "images": images,
        "fact_references": [fact["fact_id"] for fact in payload["fact_references"]]}


def check_final(payload):
    binding = payload.get("a_binding")
    if not isinstance(binding, dict):
        raise ContentError("CONFIRMED_HANDOFF_REQUIRED", "本成果没有 A 侧服务端确认交接，不能授予最终核查通过。", 409)
    # Rechecks advance revision but still bind the same confirmed strategy.
    handoff = _handoff(binding, current=True)
    request = {"task_id": binding["task_id"], "expected_revision": handoff["task"]["revision"],
        "strategy_id": binding["strategy_id"], "strategy_version": binding["strategy_version"],
        "content": final_content(payload)}
    status, result = _workflow().dispatch("/api/facts/check-final", request)
    if status != 200 or result.get("success") is not True:
        error = result.get("error") or {}
        return {"status": "pending", "content_hash": payload["content_hash"], "claims": [],
            "coverage": "incomplete", "verified_image_ids": [], "text_usable": False,
            "reason": error.get("message", "A 的最终核查未完成。"),
            "error_code": error.get("code", "FACT_CHECK_UNAVAILABLE"), "a_result": result.get("data")}
    final = result["data"]["final_check"]
    usable = final["overall"]["text_usable"]
    return {"status": "passed" if usable else "blocked", "content_hash": payload["content_hash"],
        "coverage": "complete", "claims": [deepcopy(item["check"]) for item in final["text_check"]["results"]],
        "verified_image_ids": [], "text_usable": usable, "text_check_status": final["text_check"]["status"],
        "overall_status": final["overall"]["status"], "image_check": deepcopy(final["image_check"]),
        "usable_text": deepcopy(final["usable_text"]), "a_result": deepcopy(result["data"]),
        "reason": "文字核查通过；图片视觉及图内文字仍待确认。" if usable else "成稿存在阻断或待确认项，请按 A 核查结果修改。"}
