"""Opt-in HTTP demo: real requirements understanding followed by read-only research.

Uses its own loopback server, the actual returned task identity and revision,
and never persists retrieved knowledge. No generation or fact checking occurs.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
from pathlib import Path
import sys
import threading


ROOT = Path(__file__).resolve().parents[2]
MODEL = "HUAWEI MateBook X Pro 酷睿 Ultra 微绒典藏版"


def post(port: int, path: str, payload: dict) -> tuple[int, dict]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=150)
    try:
        connection.request("POST", path, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                           {"Content-Type": "application/json; charset=utf-8"})
        response = connection.getresponse()
        return response.status, json.loads(response.read().decode("utf-8"))
    finally:
        connection.close()


def show(value: dict) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Explicitly enable the real LLM and knowledge calls.")
    parser.add_argument("--source-mode", choices=("ima", "local", "auto"),
                        help="Override knowledge mode only within this demo process.")
    args = parser.parse_args()
    if not args.live:
        parser.error("Real calls require --live. No server was started and no request was sent.")
    if args.source_mode:
        os.environ["KNOWLEDGE_SOURCE_MODE"] = args.source_mode

    missing = False
    for name in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"):
        present = bool(os.environ.get(name, "").strip())
        print(f"{name}: {'OK' if present else 'MISSING'}", flush=True)
        missing = missing or not present
    if missing:
        return 1

    sys.path.insert(0, str(ROOT))
    import app
    from src.ima_client import ImaClient
    from src.knowledge_service import KnowledgeService
    from src.product_research_service import ProductResearchService
    from src.workflow_service import set_research_service

    print(f"ima_script_exists: {ImaClient().script_path.is_file()}", flush=True)
    service = KnowledgeService()
    if service.mode == "local":
        configured = os.environ.get("LOCAL_KB_PATH", "").strip()
        print(f"LOCAL_KB_PATH: {'OK' if configured else 'MISSING'}", flush=True)
        try:
            readable = bool(configured) and Path(configured).is_dir()
        except (OSError, ValueError):
            readable = False
        print(f"local_directory_exists: {readable}", flush=True)
        if not readable:
            return 1
    if app.dispatch_v2 is None:
        print("BACKEND_NOT_READY", flush=True)
        return 1
    set_research_service(ProductResearchService(service))

    server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"Fresh app server: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        request = {
            "source": "direct",
            "user_input": f"为大学新生在开学季校园学习场景推广 {MODEL}，在小红书介绍有真实证据的产品信息，不写价格或个人体验。",
            "product_query": MODEL,
            "audience": "大学新生",
            "platform": "小红书",
            "scene": "开学季校园学习",
            "goal": "介绍有真实证据的产品信息",
            "constraints": ["不写价格或个人体验"],
        }
        status, understood = post(server.server_port, "/api/agent/understand", request)
        show({"path": "/api/agent/understand", "http_status": status,
              "request": request, "response": understood})
        if status != 201 or understood.get("success") is not True:
            return 1
        task = understood["data"]["task"]
        request = {"task_id": task["task_id"], "expected_revision": task["revision"]}
        status, response = post(server.server_port, "/api/agent/research", request)
        if status != 200 or response.get("success") is not True:
            show({"path": "/api/agent/research", "http_status": status, "request": request,
                  "error": response.get("error"), "data": response.get("data")})
            return 1
        saved = response["data"]["task"]
        research = response["data"]["research"]
        facts = research["fact_records"]
        checks = {
            "same_task": saved["task_id"] == task["task_id"],
            "new_revision": saved["revision"] > task["revision"],
            "selected_exact_model": research["selected_product_model"] == MODEL,
            "real_facts_saved": bool(facts) and saved["fact_records"] == facts,
            "no_2021_model": all(f["product_model"] == MODEL and
                                 "MateBook X Pro 2021" not in
                                 f["claim"] + f["evidence_text"] + f["source_ref"] for f in facts),
            "retrieval_not_verification": all(f["status"] in {"retrieved", "stale"} for f in facts),
            "local_is_not_live": research["knowledge_source"]["mode"] != "local" or
                                 research["knowledge_source"]["live"] is False,
            "no_strategy_created": saved["current_strategy_id"] is None,
            "understanding_did_not_research": task["fact_records"] == [],
        }
        # This is a projection of the real response, not a saved full KB dump.
        show({
            "path": "/api/agent/research", "http_status": status, "request": request,
            "response_excerpt": {
                "success": response["success"], "error": response["error"],
                "task_id": saved["task_id"], "revision": saved["revision"],
                "workflow_status": saved["workflow_status"],
                "research_status": research["status"],
                "knowledge_source": research["knowledge_source"],
                "selected_product_model": research["selected_product_model"],
                "fact_count": len(facts), "document_count": len(research["documents"]),
                "fact_record_examples": sorted(facts, key=lambda item: len(item["evidence_text"]))[:3],
                "warnings": research["warnings"], "missing_information": research["missing_information"],
                "next_action": response["data"]["next_action"],
            },
            "checks": checks,
        })
        return 0 if all(checks.values()) else 1
    except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException):
        print("RESEARCH_HTTP_DEMO_FAILED: request or response failed; raw details withheld.", flush=True)
        return 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        print("Fresh app server stopped.", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
