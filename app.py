"""华为 PC 营销内容智能体 · 前端服务入口（成员 B）

仅依赖 Python 标准库：
- GET  /            -> ui/index.html 及静态资源
- GET  /api/health  -> 是否能导入后端 run_agent
- POST /api/run     -> 调用 src.agent.run_agent(input_data)

后端未就绪时，页面会自动回退到 ui/mock.js 的模拟数据。
运行：python app.py [--port 7860]，仅监听 127.0.0.1，无鉴权，请勿暴露到公网。
"""

from __future__ import annotations

import argparse
import json
import traceback
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
UI_DIR = ROOT / "ui"
MAX_BODY = 64 * 1024
INPUT_KEYS = ("product_query", "audience", "scene", "platform", "goal", "extra_requirements")

try:
    from src.agent import run_agent  # type: ignore
    BACKEND_ERROR = None
except Exception as exc:  # 后端未完成时保持页面可用
    run_agent = None
    BACKEND_ERROR = f"{type(exc).__name__}: {exc}"


def error_result(code: str, message: str, retry: str = "") -> dict:
    return {
        "status": "error",
        "scenario": {},
        "evidence": {"facts": [], "media": []},
        "content": {},
        "checks": [],
        "questions": [],
        "conflicts": [],
        "error": {"code": code, "message": message, "retry": retry},
    }


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(UI_DIR), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def _json(self, status: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?")[0] == "/api/health":
            return self._json(200, {"backend": run_agent is not None, "detail": BACKEND_ERROR})
        return super().do_GET()

    def do_POST(self):
        if self.path != "/api/run":
            return self._json(404, error_result("NOT_FOUND", "接口不存在"))
        if run_agent is None:
            return self._json(503, error_result("BACKEND_NOT_READY", "后端 run_agent 尚未就绪", "请使用模拟模式，或等待 src/agent.py 完成。"))

        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            return self._json(400, error_result("BAD_REQUEST", "请求体为空或过大"))
        try:
            raw = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("请求体必须是 JSON 对象")
        except Exception as exc:
            return self._json(400, error_result("BAD_JSON", f"请求格式错误：{exc}"))

        # 只透传约定字段，统一为字符串
        input_data = {k: str(raw.get(k, "") or "")[:2000] for k in INPUT_KEYS}
        try:
            result = run_agent(input_data)
        except Exception as exc:
            traceback.print_exc()  # 只打印到本地终端，不把堆栈返回给页面
            return self._json(500, error_result("AGENT_ERROR", f"Agent 执行异常：{type(exc).__name__}", "查看服务端日志后重试。"))
        return self._json(200, result if isinstance(result, dict) else error_result("BAD_RESULT", "run_agent 返回值不是 dict"))

    def log_message(self, fmt, *args):
        if self.path.startswith("/api/"):
            super().log_message(fmt, *args)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=7860)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    mode = "已接入 run_agent" if run_agent else f"模拟模式（{BACKEND_ERROR}）"
    print(f"前端已启动：http://127.0.0.1:{args.port}  ·  {mode}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
