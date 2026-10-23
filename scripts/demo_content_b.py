"""Reproducible B demo against the running local server. No fake A success."""
import argparse
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen
import uuid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=7861)
    parser.add_argument("--example", choices=("study", "work", "create"), default="study")
    parser.add_argument("--output", default=".content-data/demo")
    parser.add_argument("--live", action="store_true", help="Explicitly call configured text/image services using available API credit (one image).")
    args = parser.parse_args()
    base = f"http://127.0.0.1:{args.port}/api/content"

    def call(path, payload=None, method=None):
        body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
        with urlopen(Request(base + path, data=body, headers={"Content-Type": "application/json"}, method=method or ("POST" if body else "GET")), timeout=65) as response:
            result = json.load(response)
        if not result["success"]:
            raise RuntimeError(result["error"])
        return result["data"]

    request = next(x for x in call("/examples") if x["id"] == args.example)["request"]
    request["task_id"] = "demo-" + uuid.uuid4().hex
    request["idempotency_key"] = uuid.uuid4().hex
    if args.live:
        request.update(copy_mode="llm", image_mode="ai_reference", image_count=1)
    job = call("/generate", request)
    end = time.monotonic() + 900
    while job["status"] not in ("completed", "failed") and time.monotonic() < end:
        time.sleep(1)
        job = call("/jobs/" + job["job_id"])
    if job["status"] != "completed":
        raise RuntimeError(job)
    asset = call("/" + job["asset_id"])
    if asset.get("errors"):
        raise RuntimeError({"asset_id": asset["asset_id"], "errors": asset["errors"], "note": "Copy retained; live image acceptance did not pass."})
    asset = call("/save", {"asset_id": asset["asset_id"], "expected_version": asset["version"]})
    output = Path(args.output); output.mkdir(parents=True, exist_ok=True)
    (output / "asset.json").write_text(json.dumps(asset, ensure_ascii=False, indent=2), encoding="utf-8")
    with urlopen(base + "/" + asset["asset_id"] + "/export", timeout=30) as response:
        (output / (args.example + "-review.zip")).write_bytes(response.read())
    print(json.dumps({"asset_id": asset["asset_id"], "version": asset["version"], "fact_check_status": asset["fact_check_status"], "can_publish": asset["can_publish"], "output": str(output.resolve())}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
