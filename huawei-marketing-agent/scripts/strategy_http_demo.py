"""Opt-in real HTTP flow through confirmed handoff and optional final-content checking.

No model or knowledge-source request is made unless --live is explicit. Results
are projected to stdout and kept in memory; this script writes no response or KB data.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
from pathlib import Path
import re
import sys
import threading
import time


ROOT = Path(__file__).resolve().parents[2]
MODEL = "HUAWEI MateBook X Pro 酷睿 Ultra 微绒典藏版"
ABSOLUTE_PATH = re.compile(r"(?<![\w])(?:[A-Za-z]:[\\/]|\\\\)[^\r\n\"<>|]*")
NUMBERED_2021 = re.compile(r"MateBook\s+X\s+Pro\s+2021", re.I)


def http_timeout(endpoint: str) -> float:
    if endpoint == "/api/facts/check-final":
        # This demo checks a short acceptance input with a few facts. Allow
        # the independent review and existing bounded semantic calls to finish.
        # This is only an HTTP wait, not a longer LLM timeout or a retry.
        return 1200.0
    if endpoint != "/api/strategy/generate":
        return 240.0
    from src.strategy_service import strategy_timeout_seconds
    # At most two strategy attempts, three model stages each, and the existing
    # one-time JSON-format retry. This adds waiting time, not model retries.
    return max(240.0, 12 * max(60.0, strategy_timeout_seconds()) + 60.0)


def post(port: int, endpoint: str, payload: dict) -> tuple[int, dict]:
    started = time.perf_counter()
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=http_timeout(endpoint))
    try:
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        connection.request("POST", endpoint, body, {"Content-Type": "application/json; charset=utf-8"})
        response = connection.getresponse()
        result = json.loads(response.read().decode("utf-8"))
        if not isinstance(result, dict):
            raise ValueError("response is not an object")
        print(json.dumps({"endpoint": endpoint, "http_status": response.status,
                          "elapsed_ms": round((time.perf_counter() - started) * 1000, 2)}), flush=True)
        return response.status, result
    finally:
        connection.close()


def clean(value):
    """Redact accidental machine paths from values selected for display."""
    if isinstance(value, str):
        return ABSOLUTE_PATH.sub("[本地路径已隐藏]", value)
    if isinstance(value, list):
        return [clean(item) for item in value]
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items()}
    return value


def output(value: dict) -> None:
    # ASCII JSON remains lossless and printable in Windows GBK consoles too.
    print(json.dumps(clean(value), ensure_ascii=True, indent=2, allow_nan=False), flush=True)


def error_summary(response: dict) -> dict:
    error = response.get("error") if isinstance(response.get("error"), dict) else {}
    return {"success": response.get("success"), "error": {
        "code": error.get("code", "UNKNOWN_ERROR"),
        "message": error.get("message", "请求未完成。"),
    }}


def fact_excerpt(record: dict) -> dict:
    keys = ("fact_id", "product_model", "claim", "source_ref", "source_type", "retrieved_at", "valid_until", "status")
    value = {key: record.get(key) for key in keys}
    value["evidence_text"] = str(record.get("evidence_text") or "")[:500]
    return value


def check_excerpt(batch: dict) -> dict:
    items = []
    for result in batch.get("results", []):
        item = {key: result.get(key) for key in (
            "task_id", "task_revision", "claim", "fact_references", "status", "source_refs",
            "reason", "suggested_action",
        )}
        item["evidence"] = [str(text)[:500] for text in result.get("evidence", [])]
        items.append(item)
    return {
        "counts": batch.get("counts"),
        "eligible_fact_ids": batch.get("eligible_fact_ids", []),
        "knowledge_source": {key: batch.get("knowledge_source", {}).get(key)
                             for key in ("mode", "name", "live", "status")},
        "warnings": batch.get("warnings", []),
        "errors": batch.get("errors", []),
        "diagnostics": batch.get("diagnostics", {}),
        "results": items,
    }


def acceptance_content(handoff: dict) -> tuple[dict, dict, bool]:
    """Manual check acceptance input, never an output of a creative generator."""
    records = handoff["fact_records"]
    body = "\n\n".join(record["claim"] for record in records)
    original = {
        "title": handoff["strategy"]["topic"], "body": body, "cta": "",
        "plain_text": body, "images": [],
        "fact_references": [record["fact_id"] for record in records],
    }
    changed, count = re.subn(r"\d+(?:\.\d+)?", "999", body, count=1)
    bad_body = changed + "\n\n今日到手价 4999 元，限时优惠 1000 元。"
    adverse = {**original, "body": bad_body, "plain_text": bad_body, "fact_references": []}
    return original, adverse, bool(count)


def final_excerpt(checked: dict) -> dict:
    value = {key: checked.get(key) for key in (
        "check_id", "task_id", "task_revision", "saved_task_revision", "strategy_id", "strategy_version",
        "content_digest", "content_version", "valid", "execution_status", "overall", "image_check",
        "usable_text", "warnings", "errors", "diagnostics", "next_action",
    )}
    text = checked.get("text_check", {})
    value["text_check"] = {key: text.get(key) for key in ("status", "counts", "blocking_items")}
    value["text_check"]["results"] = [
        {"field_path": item["field_path"], **check_excerpt({"results": [item["check"]]})["results"][0]}
        for item in text.get("results", [])
    ]
    value["knowledge_source"] = {key: (checked.get("knowledge_source") or {}).get(key)
                                 for key in ("mode", "name", "live", "status")}
    return value


def environment_ready(source_mode: str) -> bool:
    required = ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL")
    missing = []
    for name in required:
        present = bool(os.environ.get(name, "").strip())
        print(f"{name}: {'OK' if present else 'MISSING'}", flush=True)
        if not present:
            missing.append(name)

    mock = os.environ.get("USE_MOCK", "").strip().casefold()
    mock_disabled = mock in {"false", "0", "no", "off"}
    print(f"USE_MOCK: {'OK' if mock_disabled else 'MISSING'}", flush=True)
    if not mock_disabled:
        missing.append("USE_MOCK")

    if source_mode == "local":
        configured_path = os.environ.get("LOCAL_KB_PATH", "").strip()
        try:
            directory_exists = bool(configured_path) and Path(configured_path).is_dir()
        except (OSError, ValueError):
            directory_exists = False
        print(f"LOCAL_KB_PATH: {'OK' if directory_exists else 'MISSING'}", flush=True)
        if not directory_exists:
            missing.append("LOCAL_KB_PATH")

    print(f"KNOWLEDGE_SOURCE_MODE: {'OK' if source_mode in {'ima', 'local', 'auto'} else 'MISSING'}", flush=True)
    if source_mode not in {"ima", "local", "auto"}:
        missing.append("KNOWLEDGE_SOURCE_MODE")
    return not missing


def finish_server(server, thread, *, keep: bool, task: dict, failure_stage: str) -> None:
    try:
        if keep:
            output({"server_retained": True, "address": f"http://127.0.0.1:{server.server_port}",
                    "task_id": task.get("task_id"), "revision": task.get("revision"),
                    "workflow_status": task.get("workflow_status"), "failure_stage": failure_stage,
                    "message": "服务与任务保留，未重试；Ctrl+C 可停止此服务。"})
            while thread.is_alive():
                thread.join(timeout=30)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        print("fresh_loopback_server_stopped", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Explicitly enable real LLM and read-only knowledge calls.")
    parser.add_argument("--source-mode", choices=("ima", "local", "auto"),
                        help="Override KNOWLEDGE_SOURCE_MODE for this process only.")
    parser.add_argument("--keep-server-on-failure", action="store_true",
                        help="Keep the same server and task alive for diagnosis after failure; no retries.")
    parser.add_argument("--check-final", action="store_true",
                        help="Check manual acceptance text, then tampered text, after confirmed real handoff.")
    args = parser.parse_args()
    if not args.live:
        parser.error("Real calls require --live. No server was started and no request was sent.")

    if args.source_mode:
        os.environ["KNOWLEDGE_SOURCE_MODE"] = args.source_mode
    source_mode = os.environ.get("KNOWLEDGE_SOURCE_MODE", "ima").strip().casefold()
    if not environment_ready(source_mode):
        return 1

    sys.path.insert(0, str(ROOT))
    import app
    from src.knowledge_service import KnowledgeService
    from src.product_research_service import ProductResearchService
    from src.workflow_service import set_research_service

    if app.dispatch_v2 is None:
        print("BACKEND_NOT_READY", flush=True)
        return 1
    set_research_service(ProductResearchService(KnowledgeService()))

    server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"fresh_loopback_server_started: {bool(server.server_port)}", flush=True)
    report = {"live": True, "knowledge_source_mode_requested": source_mode}
    task, completed, failure_stage = {}, False, "understand"
    try:
        request = {
            "source": "direct",
            "user_input": (
                f"为有移动学习和轻办公需求的大学生，在开学季校园学习场景介绍 {MODEL}。"
                "只使用本任务检索并核查通过的产品事实，不推断价格、优惠、体验或证据以外的参数。"
            ),
            "product_query": MODEL,
            "audience": "有移动学习和轻办公需求的大学生",
            "platform": "小红书",
            "scene": "开学季校园学习",
            "goal": "基于可核查产品事实规划一个可信的推广主题",
            "constraints": ["不写价格、优惠、个人体验、排名或证据未支持的参数"],
        }
        status, response = post(server.server_port, "/api/agent/understand", request)
        if status != 201 or response.get("success") is not True:
            report["understand"] = {"http_status": status, **error_summary(response)}
            output(report)
            return 1
        task = response["data"]["task"]
        report["understand"] = {
            "http_status": status, "summary": response["data"]["understanding"]["summary"],
            "questions": response["data"]["understanding"]["questions"],
            "task_id": task["task_id"], "revision": task["revision"],
            "workflow_status": task["workflow_status"],
        }
        if task["workflow_status"] != "ready_for_strategy":
            report["stopped_at"] = "understand"
            report["reason"] = "需求未达到 ready_for_strategy；未进行后续步骤。"
            output(report)
            return 1

        failure_stage = "research"
        request = {"task_id": task["task_id"], "expected_revision": task["revision"]}
        status, response = post(server.server_port, "/api/agent/research", request)
        if status != 200 or response.get("success") is not True:
            report["research"] = {"http_status": status, **error_summary(response)}
            output(report)
            return 1
        task = response["data"]["task"]
        research = response["data"]["research"]
        records = research.get("fact_records", [])
        no_2021 = all(not NUMBERED_2021.search(" ".join(str(record.get(key, "")) for key in (
            "product_model", "claim", "evidence_text", "source_ref",
        ))) for record in records)
        exact_records = [record for record in records
                         if record.get("product_model") == MODEL and record.get("status") in {"retrieved", "supported"}]
        report["research"] = {
            "http_status": status, "status": research.get("status"),
            "knowledge_source": {key: research.get("knowledge_source", {}).get(key)
                                 for key in ("mode", "name", "live", "status")},
            "selected_product_model": research.get("selected_product_model"),
            "candidate_models": research.get("candidate_models", []),
            "document_count": len(research.get("documents", [])),
            "candidate_fact_count": len(records), "exact_model_fact_count": len(exact_records),
            "contains_2021_model": not no_2021,
            "facts": [fact_excerpt(record) for record in exact_records[:3]],
            "warnings": research.get("warnings", []),
        }
        if research.get("selected_product_model") != MODEL or not no_2021 or not exact_records:
            report["stopped_at"] = "research"
            report["reason"] = "未获得无型号混用的精确型号候选事实；未核查或生成策略。"
            output(report)
            return 1

        unique = {}
        for record in exact_records:
            unique.setdefault(record["claim"], record)
        selected = sorted(unique.values(), key=lambda item: (len(item.get("claim", "")), len(item.get("evidence_text", ""))))[:3]
        check_request = {
            "task_id": task["task_id"], "expected_revision": task["revision"],
            "claims": [{"claim": record["claim"], "fact_references": [record["fact_id"]]} for record in selected]
                      + [{"claim": "今日到手价 4999 元，限时优惠 1000 元。", "fact_references": []}],
        }
        failure_stage = "facts/check"
        status, response = post(server.server_port, "/api/facts/check", check_request)
        if status != 200 or response.get("success") is not True:
            report["facts_check"] = {"http_status": status, **error_summary(response)}
            output(report)
            return 1
        task = response["data"]["task"]
        fact_check = response["data"]["fact_check"]
        report["facts_check"] = {"http_status": status, "task_revision": task["revision"], **check_excerpt(fact_check)}
        eligible_ids = set(fact_check.get("eligible_fact_ids", []))
        if not eligible_ids:
            report["stopped_at"] = "facts/check"
            report["reason"] = "本轮没有取得策略可用的事实白名单；没有调用策略生成。"
            output(report)
            return 1

        failure_stage = "strategy/generate"
        request = {"task_id": task["task_id"], "expected_revision": task["revision"]}
        status, response = post(server.server_port, "/api/strategy/generate", request)
        if status != 200 or response.get("success") is not True:
            data = response.get("data") if isinstance(response.get("data"), dict) else {}
            if isinstance(data.get("task"), dict):
                task = data["task"]
            report["strategy_generate"] = {
                "http_status": status, **error_summary(response),
                "blocking_items": data.get("blocking_items", []),
                "fact_check": check_excerpt(data.get("fact_check", {})) if isinstance(data.get("fact_check"), dict) else None,
                "next_action": data.get("next_action"),
                "diagnostics": data.get("diagnostics", {}),
            }
            output(report)
            return 1
        task = response["data"]["task"]
        strategy = response["data"]["strategy"]
        generated_check = response["data"]["fact_check"]
        used_ids = set(strategy.get("fact_references", []))
        report["strategy_generate"] = {
            "http_status": status,
            "task_revision": task["revision"],
            "attempts": response["data"].get("attempts"),
            "diagnostics": response["data"].get("diagnostics", {}),
            "workflow_status": task["workflow_status"],
            "strategy": strategy,
            "strategy_fact_check": check_excerpt(generated_check),
            "all_strategy_facts_supported": (
                bool(generated_check.get("results"))
                and all(item.get("status") == "supported" for item in generated_check["results"])
            ),
            "references_within_eligible_fact_set": used_ids <= eligible_ids,
            "next_action": response["data"].get("next_action"),
        }
        if (task["workflow_status"] != "awaiting_user_confirmation"
                or strategy.get("confirmation_status") != "pending"
                or not report["strategy_generate"]["all_strategy_facts_supported"]
                or not report["strategy_generate"]["references_within_eligible_fact_set"]):
            report["stopped_at"] = "strategy/generate"
            report["reason"] = "生成结果未满足待确认和事实支持条件；没有提交确认。"
            output(report)
            return 1

        request = {
            "task_id": task["task_id"], "expected_revision": task["revision"],
            "strategy_id": strategy["strategy_id"], "strategy_version": strategy["strategy_version"],
        }
        failure_stage = "strategy/confirm"
        status, response = post(server.server_port, "/api/strategy/confirm", request)
        if status != 200 or response.get("success") is not True:
            report["strategy_confirm"] = {"http_status": status, **error_summary(response)}
            output(report)
            return 1
        task = response["data"]["task"]
        strategy = response["data"]["strategy"]
        report["strategy_confirm"] = {
            "http_status": status, "workflow_status": task["workflow_status"],
            "task_id": task["task_id"], "revision": task["revision"],
            "strategy_id": strategy["strategy_id"], "strategy_version": strategy["strategy_version"],
            "confirmation_status": strategy["confirmation_status"],
            "confirmed_at_task_revision": strategy["confirmed_at_task_revision"],
        }
        if task["workflow_status"] != "strategy_confirmed" or strategy["confirmation_status"] != "confirmed":
            report["stopped_at"] = "strategy/confirm"
            report["reason"] = "服务端没有确认当前策略；未请求图文交接。"
            output(report)
            return 1

        request = {
            "task_id": task["task_id"], "expected_revision": task["revision"],
            "strategy_id": strategy["strategy_id"], "strategy_version": strategy["strategy_version"],
        }
        failure_stage = "strategy/handoff"
        status, response = post(server.server_port, "/api/strategy/handoff", request)
        if status != 200 or response.get("success") is not True:
            report["handoff"] = {"http_status": status, **error_summary(response)}
            output(report)
            return 1
        handoff = response["data"]["handoff"]
        handoff_facts = handoff.get("fact_records", [])
        handoff_eligible = {record.get("fact_id") for record in handoff_facts}
        report["handoff"] = {
            "http_status": status, "implementation_status": response["data"].get("implementation_status"),
            "task_id": handoff.get("task", {}).get("task_id"),
            "task_revision": handoff.get("task", {}).get("revision"),
            "strategy_id": handoff.get("strategy", {}).get("strategy_id"),
            "strategy_version": handoff.get("strategy", {}).get("strategy_version"),
            "adopted_fact_ids": sorted(handoff_eligible),
            "adopted_facts": [fact_excerpt(record) for record in handoff_facts],
            "image_status": handoff.get("image_status"),
            "images": handoff.get("images", []),
            "source_limits": handoff.get("source_limits", []),
            "warnings": handoff.get("warnings", []),
        }
        checks = {
            "single_task_throughout": handoff.get("task", {}).get("task_id") == report["understand"]["task_id"],
            "selected_exact_model": research.get("selected_product_model") == MODEL,
            "no_2021_model": no_2021,
            "only_strategy_references_handed_off": used_ids == handoff_eligible and handoff_eligible <= eligible_ids,
            "images_remain_unknown": handoff.get("image_status") == "unknown",
            "server_confirmed_strategy": handoff.get("strategy", {}).get("confirmation_status") == "confirmed",
        }
        if args.check_final and all(checks.values()):
            good_content, bad_content, tampered_parameter = acceptance_content(handoff)
            report["final_check_input_label"] = "核查验收输入：依据本次真实交接手工构造；图文生成模块尚未接入。"
            report["final_check_inputs"] = {"A": good_content, "B": bad_content,
                                             "parameter_tampered_in_B": tampered_parameter}
            task = handoff["task"]
            previous_check_id = None
            for label, draft in (("A", good_content), ("B", bad_content)):
                failure_stage = "facts/check-final/" + label
                request = {"task_id": task["task_id"], "expected_revision": task["revision"],
                           "strategy_id": strategy["strategy_id"], "strategy_version": strategy["strategy_version"],
                           "content": draft}
                status, response = post(server.server_port, "/api/facts/check-final", request)
                data = response.get("data") if isinstance(response.get("data"), dict) else {}
                if isinstance(data.get("task"), dict):
                    task = data["task"]
                checked = data.get("final_check")
                report["final_check_" + label] = {"http_status": status,
                    **({"final_check": final_excerpt(checked)} if isinstance(checked, dict) else {}),
                    **(error_summary(response) if response.get("success") is not True else {})}
                if status != 200 or response.get("success") is not True or not isinstance(checked, dict):
                    output(report)
                    return 1
                text_status = checked["text_check"]["status"]
                checks["final_" + label + "_expected_text_result"] = text_status == ("passed" if label == "A" else "blocked")
                checks["final_" + label + "_images_unknown"] = (
                    checked["image_check"]["status"] == "unknown"
                    and checked["image_check"]["visual_check_performed"] is False
                    and checked["overall"]["completed"] is False
                    and checked["overall"]["ready_to_publish"] is False)
                checks["final_" + label + "_bound_to_current_strategy"] = (
                    checked["task_id"] == task["task_id"] and checked["strategy_id"] == strategy["strategy_id"]
                    and checked["strategy_version"] == strategy["strategy_version"])
                if label == "A":
                    previous_check_id = checked["check_id"]
                    checks["final_A_text_preserved"] = (checked.get("usable_text") or {}).get("plain_text") == draft["plain_text"]
                    if not checks["final_A_expected_text_result"]:
                        report["checks"] = checks
                        output(report)
                        return 1
                else:
                    from src.workflow_service import REPOSITORY
                    audits = REPOSITORY.get_final_checks(task["task_id"], content=bad_content)
                    old = next(item for item in audits if item["check_id"] == previous_check_id)
                    checks["edited_content_invalidates_A"] = old["valid"] is False
                    checks["final_B_no_usable_text"] = checked.get("usable_text") is None
                    checks["final_B_includes_tampered_parameter"] = tampered_parameter
                    report["previous_final_check_valid_after_edit"] = old["valid"]
        report["checks"] = checks
        completed = all(checks.values())
        report["result"] = "success" if completed else "failed_validation"
        output(report)
        return 0 if all(checks.values()) else 1
    except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException):
        report["result"] = "failed"
        report["error"] = "HTTP request or response failed; raw details withheld."
        output(report)
        return 1
    finally:
        finish_server(server, thread, keep=args.keep_server_on_failure and not completed,
                      task=task, failure_stage=failure_stage)


if __name__ == "__main__":
    raise SystemExit(main())
