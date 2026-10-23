"""Opt-in real HTTP demo; starts its own fresh server and sends exactly two turns."""

from __future__ import annotations

import argparse
import http.client
import json
import os
from pathlib import Path
import sys
import threading


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def post(port: int, path: str, payload: dict) -> tuple[int, dict]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=150)
    try:
        connection.request("POST", path, json.dumps(payload, ensure_ascii=False).encode("utf-8"), {
            "Content-Type": "application/json; charset=utf-8",
        })
        response = connection.getresponse()
        result = json.loads(response.read().decode("utf-8"))
        print(json.dumps({"path": path, "request": payload, "http_status": response.status,
                          "response": result}, ensure_ascii=False, indent=2), flush=True)
        return response.status, result
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Explicitly send the synthetic requirements to the configured LLM.")
    args = parser.parse_args()
    if not args.live:
        parser.error("Real LLM calls require --live. No request was sent.")
    missing = []
    for name in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"):
        present = bool(os.environ.get(name, "").strip())
        print(f"{name}: {'OK' if present else 'MISSING'}", flush=True)
        if not present:
            missing.append(name)
    if missing:
        return 1

    import app
    if app.dispatch_v2 is None:
        print("BACKEND_NOT_READY", flush=True)
        return 1

    # OS assigns a fresh port: never reuse or terminate an unrelated old server.
    server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"Fresh app server: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        status, first = post(server.server_port, "/api/agent/understand", {
            "source": "opportunity",
            "user_input": "想按这个机会给大学新生准备开学季电脑推广内容，其他信息稍后补充。",
            "opportunity_context": {
                "audience": "大学新生", "scene": "开学季", "source_label": "opportunity-board",
            },
        })
        if status != 201 or first.get("success") is not True:
            return 1
        task = first["data"]["task"]
        status, second = post(server.server_port, "/api/agent/continue", {
            "task_id": task["task_id"], "expected_revision": task["revision"],
            "user_input": "产品是 HUAWEI MateBook X Pro 酷睿 Ultra 微绒典藏版；受众改为研究生；发布在小红书；目标是介绍有来源支持的学习场景；清空场景，不写价格和个人体验。",
            "updates": {
                "product_query": "HUAWEI MateBook X Pro 酷睿 Ultra 微绒典藏版",
                "platform": "小红书", "goal": "介绍有来源支持的学习场景",
                "constraints": ["不写价格和个人体验"],
            },
            "clear_fields": ["scene"],
        })
        if status != 200 or second.get("success") is not True:
            return 1
        updated = second["data"]["task"]
        checks = {
            "one_question": len(first["data"]["understanding"]["questions"]) == 1,
            "initial_collecting": task["workflow_status"] == "collecting_requirements",
            "audience_understood": task["audience"] == "大学新生",
            "opportunity_scene_understood": task["scene"] == "开学季",
            "same_task": updated["task_id"] == task["task_id"],
            "new_revision": updated["revision"] > task["revision"],
            "original_input_preserved": updated["user_input"] == task["user_input"],
            "source_preserved": updated["source"] == "opportunity" and updated["opportunity_context"] == task["opportunity_context"],
            "audience_changed_by_model": updated["audience"] == "研究生",
            "scene_cleared": updated["scene"] == "" and updated["field_status"]["scene"] == "cleared",
            "ready_for_strategy": updated["workflow_status"] == "ready_for_strategy",
            "no_question_when_ready": second["data"]["interpretation"]["questions"] == [],
            "no_fact_verification_claim": updated["fact_records"] == [],
        }
        print(json.dumps({"checks": checks}, ensure_ascii=False, indent=2), flush=True)
        return 0 if all(checks.values()) else 1
    except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException):
        print("HTTP_DEMO_FAILED: local request or response failed; details withheld.", flush=True)
        return 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        print("Fresh app server stopped.", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
