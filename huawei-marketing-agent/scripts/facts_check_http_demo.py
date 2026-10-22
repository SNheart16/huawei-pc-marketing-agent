"""Opt-in real HTTP flow: understand -> read-only research -> pre-generation fact check.

The demonstration keeps request/response data in memory and prints only bounded
claim/evidence excerpts. Pass --live explicitly before any LLM or KB call.
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


ROOT = Path(__file__).resolve().parents[2]
MODEL = "HUAWEI MateBook X Pro 酷睿 Ultra 微绒典藏版"
NUMBER = re.compile(
    r"(?<!\d)(\d+(?:\.\d+)?)(\s*(?:GHz|MHz|mAh|Wh|GB|TB|MB|kg|mm|cm|Hz|nit|nits|%|g|W|英寸|小时|分钟|克|千克|毫米|厘米|元))?",
    re.I,
)


def post(port: int, path: str, payload: dict) -> tuple[int, dict]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=180)
    try:
        connection.request("POST", path, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                           {"Content-Type": "application/json; charset=utf-8"})
        response = connection.getresponse()
        return response.status, json.loads(response.read().decode("utf-8"))
    finally:
        connection.close()


def print_json(value: dict) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2), flush=True)


def tamper_parameter(text: str) -> str | None:
    matches = list(NUMBER.finditer(text))
    # Prefer a measurement to a heading/section number, never alter a model year.
    candidates = [item for item in matches
                  if not (len(item.group(1)) == 4 and item.group(1).startswith("20"))]
    match = next((item for item in candidates if item.group(2)), candidates[0] if candidates else None)
    if not match:
        return None
    value = float(match.group(1))
    replacement = str(int(value + 1)) if value.is_integer() else str(round(value + 1, 2))
    return text[:match.start(1)] + replacement + text[match.end(1):]


def response_summary(response: dict) -> dict:
    data = response.get("data") if isinstance(response.get("data"), dict) else {}
    batch = data.get("fact_check") if isinstance(data.get("fact_check"), dict) else {}
    results = batch.get("results") if isinstance(batch.get("results"), list) else []
    return {
        "success": response.get("success"),
        "error": response.get("error"),
        "task_id": batch.get("task_id"),
        "checked_task_revision": batch.get("task_revision"),
        "saved_task_revision": batch.get("saved_task_revision"),
        "knowledge_source": {
            key: (batch.get("knowledge_source") or {}).get(key)
            for key in ("mode", "name", "live", "status")
        },
        "counts": batch.get("counts"),
        "eligible_fact_ids": batch.get("eligible_fact_ids"),
        "execution_status": batch.get("execution_status"),
        "next_action": batch.get("next_action"),
        "warnings": batch.get("warnings", []),
        "items": [{
            "status": item.get("status"),
            "claim": item.get("claim", "")[:240],
            "fact_references": item.get("fact_references", []),
            "evidence": [text[:300] for text in item.get("evidence", [])],
            "source_refs": item.get("source_refs", []),
            "reason": item.get("reason"),
            "suggested_action": item.get("suggested_action"),
        } for item in results],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Explicitly enable real LLM and read-only KB calls.")
    parser.add_argument("--source-mode", choices=("ima", "local", "auto"),
                        help="Override knowledge source mode for this process only.")
    args = parser.parse_args()
    if not args.live:
        parser.error("Real calls require --live. No server was started and no request was sent.")
    if args.source_mode:
        os.environ["KNOWLEDGE_SOURCE_MODE"] = args.source_mode

    required = ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL")
    missing = []
    for name in required:
        present = bool(os.environ.get(name, "").strip())
        print(f"{name}: {'OK' if present else 'MISSING'}", flush=True)
        if not present:
            missing.append(name)
    mock_value = os.environ.get("USE_MOCK", "").strip().casefold()
    mock_ok = mock_value in {"false", "0", "no", "off"}
    print(f"USE_MOCK: {'OK' if mock_ok else 'MISSING'}", flush=True)
    mode = os.environ.get("KNOWLEDGE_SOURCE_MODE", "ima").strip().casefold()
    print(f"KNOWLEDGE_SOURCE_MODE: {'OK' if mode in {'ima', 'local', 'auto'} else 'MISSING'}", flush=True)
    if mode == "local":
        configured_path = os.environ.get("LOCAL_KB_PATH", "").strip()
        try:
            local_ok = bool(configured_path) and Path(configured_path).is_dir()
        except (OSError, ValueError):
            local_ok = False
        print(f"LOCAL_KB_PATH: {'OK' if local_ok else 'MISSING'}", flush=True)
        if not local_ok:
            missing.append("LOCAL_KB_PATH")
    if missing or not mock_ok or mode not in {"ima", "local", "auto"}:
        return 1

    sys.path.insert(0, str(ROOT))
    import app
    from src.product_research_service import ProductResearchService
    from src.knowledge_service import KnowledgeService
    from src.workflow_service import set_research_service

    if app.dispatch_v2 is None:
        print("BACKEND_NOT_READY", flush=True)
        return 1
    set_research_service(ProductResearchService(KnowledgeService()))
    server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"fresh_loopback_server_started: {bool(server.server_port)}", flush=True)
    try:
        understand_request = {
            "source": "direct",
            "user_input": f"为大学生在开学季核对 {MODEL} 的可用产品事实；不要推断价格或促销。",
            "product_query": MODEL,
            "audience": "有移动学习和轻办公需求的大学生",
            "platform": "门店朋友圈",
            "scene": "开学季校园学习",
            "goal": "核对可用的产品事实",
            "constraints": ["不推断价格、优惠、体验或证据未支持的参数"],
        }
        status, understood = post(server.server_port, "/api/agent/understand", understand_request)
        if status != 201 or understood.get("success") is not True:
            print_json({"stage": "understand", "http_status": status, "error": understood.get("error")})
            return 1
        first_task = understood["data"]["task"]
        research_request = {"task_id": first_task["task_id"], "expected_revision": first_task["revision"]}
        status, researched = post(server.server_port, "/api/agent/research", research_request)
        if status != 200 or researched.get("success") is not True:
            print_json({"stage": "research", "http_status": status, "error": researched.get("error")})
            return 1
        task = researched["data"]["task"]
        research = researched["data"]["research"]
        facts = research.get("fact_records", [])
        if research.get("selected_product_model") != MODEL or not facts:
            print_json({"stage": "research", "status": research.get("status"),
                        "selected_product_model": research.get("selected_product_model"),
                        "fact_count": len(facts), "warnings": research.get("warnings", [])})
            return 1
        candidates = [item for item in facts if item.get("product_model") == MODEL]
        originals = candidates[:3]
        numeric = next(((item, tamper_parameter(item["claim"])) for item in candidates
                        if tamper_parameter(item["claim"])), None)
        if not originals or numeric is None:
            print_json({"stage": "fact_selection", "fact_count": len(candidates),
                        "error": "没有足够的精确型号候选事实或可安全构造的数字篡改项。"})
            return 1

        claims = [{"claim": item["claim"], "fact_references": [item["fact_id"]]} for item in originals]
        # One conservative rewrite exercises semantic comparison using a single necessary evidence snippet.
        claims.append({"claim": "这款产品的" + originals[0]["claim"],
                       "fact_references": [originals[0]["fact_id"]]})
        tampered_fact, tampered_claim = numeric
        claims.append({"claim": tampered_claim, "fact_references": [tampered_fact["fact_id"]]})
        claims.append({"claim": "今日到手价 4999 元，限时优惠 1000 元。", "fact_references": []})
        check_request = {"task_id": task["task_id"], "expected_revision": task["revision"], "claims": claims}
        http_status, checked = post(server.server_port, "/api/facts/check", check_request)
        summary = response_summary(checked)
        summary["http_status"] = http_status
        summary["research"] = {
            "status": research.get("status"),
            "knowledge_source": {key: research.get("knowledge_source", {}).get(key)
                                 for key in ("mode", "name", "live", "status")},
            "selected_product_model": research.get("selected_product_model"),
            "candidate_fact_count": len(facts),
            "candidate_models": research.get("candidate_models", []),
            "contains_2021_model": any(
                re.search(r"MateBook\s+X\s+Pro\s+2021", "\n".join(
                    str(item.get(key, "")) for key in ("product_model", "claim", "evidence_text", "source_ref")
                ), re.I) for item in facts
            ),
        }
        summary["request_summary"] = {
            "task_id": check_request["task_id"], "expected_revision": check_request["expected_revision"],
            "claims": [{"claim": item["claim"][:200], "fact_references": item["fact_references"]} for item in claims],
        }
        print_json(summary)
        results = summary["items"]
        if not results:
            return 1
        tampered_result = results[len(originals) + 1]
        offer_result = results[-1]
        checks = [
            summary.get("success") is True,
            summary.get("knowledge_source", {}).get("mode") in ({"ima", "local"} if mode == "auto" else {mode}),
            summary["research"]["selected_product_model"] == MODEL,
            summary["research"]["contains_2021_model"] is False,
            tampered_result["status"] != "supported",
            offer_result["status"] == "unsupported",
        ]
        return 0 if all(checks) else 1
    except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException):
        print("FACT_CHECK_HTTP_DEMO_FAILED: request or response failed; raw details withheld.", flush=True)
        return 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        print("fresh_loopback_server_stopped", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
