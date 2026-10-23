"""华为 PC 营销内容智能体 · 前端服务入口（成员 B）

仅依赖 Python 标准库：
- GET  /            -> ui/index.html 及静态资源
- GET  /api/health  -> 是否能导入后端 run_agent
- POST /api/run     -> 调用 src.agent.run_agent(input_data)

仅调用真实后端；后端未就绪时返回安全错误，不回退模拟数据。
运行：python app.py [--port 7860]，仅监听 127.0.0.1，无鉴权，请勿暴露到公网。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
UI_DIR = ROOT / "ui"
BACKEND_DIR = ROOT / "huawei-marketing-agent"
MAX_BODY = 64 * 1024
INPUT_KEYS = ("product_query", "audience", "scene", "platform", "goal", "extra_requirements")

# 前后端位于同一仓库的不同目录，导入不依赖启动终端的工作目录。
sys.path.insert(0, str(BACKEND_DIR))
try:
    from src.agent import run_agent
    from src.workflow_service import V2_ROUTES, dispatch as dispatch_v2
    BACKEND_ERROR = None
except Exception:
    run_agent = None
    V2_ROUTES = set()
    dispatch_v2 = None
    BACKEND_ERROR = "真实后端导入失败，请检查后端文件及运行环境。"


def error_result(code: str, message: str, retry: str = "") -> dict:
    return {
        "schema_version": "1.0",
        "status": "error",
        "status_message": message,
        "knowledge_source": {
            "mode": "local" if os.environ.get("KNOWLEDGE_SOURCE_MODE") == "local" else "ima",
            "name": "任德耀新建华为PC知识库",
            "live": False,
            "status": "unavailable",
            "message": "本次请求尚未完成知识库读取。",
        },
        "scenario": {},
        "evidence": [],
        "content": None,
        "checks": {
            "facts": [], "images": [], "compliance": [],
            "risks": [code], "missing_information": [retry] if retry else [],
            "questions": [],
        },
    }


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(UI_DIR), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def _json(self, status: int, data: dict, v2: bool = False) -> None:
        try:
            body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError):
            status = 502
            fallback = ({"success": False, "data": None, "error": {"code": "BAD_RESULT", "message": "v2 后端返回结果格式不正确。"}}
                        if v2 else error_result("BAD_RESULT", "后端返回结果格式不正确。"))
            body = json.dumps(fallback, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        if self.path.split("?")[0] == "/api/health":
            return self._json(200, {"backend": run_agent is not None, "detail": BACKEND_ERROR})
        return super().do_GET()

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        is_v2 = path in V2_ROUTES
        if path != "/api/run" and not is_v2:
            return self._json(404, error_result("NOT_FOUND", "接口不存在"))
        if path == "/api/run" and run_agent is None:
            return self._json(503, error_result("BACKEND_NOT_READY", "真实后端尚未就绪。", "请检查后端文件和运行环境后重试。"))
        if is_v2 and dispatch_v2 is None:
            return self._json(503, {"success": False, "data": None, "error": {"code": "BACKEND_NOT_READY", "message": "v2 工作流后端尚未就绪。"}})

        def request_error(status: int, code: str, message: str):
            if is_v2:
                return self._json(status, {"success": False, "data": None, "error": {"code": code, "message": message}})
            return self._json(status, error_result(code, message))

        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1 or self.headers.get("Transfer-Encoding"):
            return request_error(400, "BAD_REQUEST", "请求长度格式不正确。")
        try:
            length = int(lengths[0])
        except (TypeError, ValueError, OverflowError):
            return request_error(400, "BAD_REQUEST", "请求长度格式不正确。")
        if length <= 0 or length > MAX_BODY:
            return request_error(400, "BAD_REQUEST", "请求体为空或过大。")
        try:
            self.connection.settimeout(15)
            raw = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(raw, dict):
                raise ValueError
        except (ValueError, UnicodeError, OSError, RecursionError):
            return request_error(400, "BAD_JSON", "请求体必须是有效的 JSON 对象。")

        if is_v2:
            status, result = dispatch_v2(path, raw)
            return self._json(status, result, v2=True)

        # 只透传约定字段；缺失或 null 交由真实 Agent 返回 needs_input。
        input_data = {k: raw.get(k) if raw.get(k) is not None else "" for k in INPUT_KEYS}
        if any(not isinstance(value, str) or len(value) > 2000 for value in input_data.values()):
            return request_error(400, "BAD_INPUT", "输入字段必须为不超过 2000 字的文本。")
        try:
            result = run_agent(input_data)
        except Exception:
            return self._json(500, error_result("AGENT_ERROR", "真实生成暂未完成；错误详情已隐藏。", "请检查服务运行环境后重试。"))
        if not isinstance(result, dict):
            return self._json(502, error_result("BAD_RESULT", "后端返回结果格式不正确。"))
        return self._json(200, result)

    def log_message(self, fmt, *args):
        # 不记录请求路径、正文或后端异常，避免将用户资料或凭证写入日志。
        pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=7860)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    mode = "已接入真实 run_agent" if run_agent else "真实后端尚未就绪"
    print(f"前端已启动：http://127.0.0.1:{args.port}  ·  {mode}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
