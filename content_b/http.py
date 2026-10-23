"""Small route adapter for the existing stdlib server; leaves /api/run untouched."""
import io
import json
import os
import re
import threading
from urllib.parse import urlsplit, parse_qs
import zipfile

from .contracts import ContentError
from .providers import ROOT
from .service import ContentService
from .references import register_reference

_service = None
_lock = threading.Lock()


def service():
    global _service
    with _lock:
        if _service is None:
            _service = ContentService(os.environ.get("CONTENT_DATA_DIR"))
        return _service


def body(handler):
    lengths = handler.headers.get_all("Content-Length", [])
    try:
        if len(lengths) != 1 or handler.headers.get("Transfer-Encoding"):
            raise ValueError()
        length = int(lengths[0])
        limit = 12 * 1024 * 1024 if urlsplit(handler.path).path == '/api/content/references' else 256 * 1024
        if not 0 < length <= limit:
            raise ValueError()
        handler.connection.settimeout(15)
        value = json.loads(handler.rfile.read(length).decode("utf-8"), parse_constant=lambda x: (_ for _ in ()).throw(ValueError()))
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, UnicodeError, OSError, RecursionError):
        raise ContentError("BAD_REQUEST", "请求须为标准 JSON 对象，且不超过该接口允许的大小。") from None


def binary(handler, value, mime, filename=None):
    handler.send_response(200)
    handler.send_header("Content-Type", mime)
    handler.send_header("Content-Length", str(len(value)))
    if filename:
        handler.send_header("Content-Disposition", f'attachment; filename="{filename}"')
    if mime == "image/svg+xml":
        handler.send_header("Content-Security-Policy", "default-src 'none'; img-src data:; style-src 'unsafe-inline'; sandbox")
    handler.end_headers()
    try:
        handler.wfile.write(value)
    except (BrokenPipeError, ConnectionResetError):
        pass


def route(handler):
    path = urlsplit(handler.path).path
    if not path.startswith("/api/content"):
        return False
    try:
        host = urlsplit("http://" + handler.headers.get("Host", "")).hostname
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise ContentError("HOST_DENIED", "此服务只接受本机地址。", 403)
        # Reject cross-origin browser writes to the local unauthenticated service.
        origin = handler.headers.get("Origin")
        if handler.command != "GET" and origin:
            parsed = urlsplit(origin)
            if parsed.netloc != handler.headers.get("Host") or parsed.scheme not in ("http", "https"):
                raise ContentError("ORIGIN_DENIED", "不接受跨来源写入。", 403)
        svc, result, code = service(), None, 200
        if handler.command == "GET":
            if path == "/api/content/capabilities":
                result = {"schema_version": "content-b/1.0", "copy_modes": ["assembly", "llm"],
                          "llm_configured": all(os.environ.get(k) for k in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL")),
                          "fact_check_configured": bool(os.environ.get("FACT_CHECK_FINAL_URL")), "image_mode": "pregenerated",
                          "image_modes": ["pregenerated", "layout"], "image_generation_configured": False,
                          "image_generation_enabled": False,
                          "note": "本演示使用预生成素材，不调用生图 API；图片视觉核查仍为 unknown。"}
            elif path == "/api/content/examples":
                result = json.loads((ROOT / "content_b" / "examples.json").read_text(encoding="utf-8"))
            elif path == "/api/content/catalog":
                query = parse_qs(urlsplit(handler.path).query)
                result = svc.media.list(query.get("model", [""])[0], query.get("platform", [""])[0])
            elif re.fullmatch(r'/api/content/references/ref-[a-f0-9]{32}\.(png|jpg)', path):
                reference = svc.media.media_dir.parent / 'references' / path.rsplit('/', 1)[1]
                if not reference.is_file():
                    raise ContentError('REFERENCE_MISSING', '参考原图不存在。', 404)
                binary(handler, reference.read_bytes(), 'image/png' if reference.suffix == '.png' else 'image/jpeg')
                return True
            elif path == "/api/content":
                result = svc.store.list(parse_qs(urlsplit(handler.path).query).get("task_id", [None])[0])
            elif re.fullmatch(r"/api/content/jobs/job-[a-f0-9]{32}", path):
                result = svc.get_job(path.rsplit("/", 1)[1])
                result = {k: v for k, v in result.items() if k not in ("key", "fingerprint")}
            elif re.fullmatch(r"/api/content/media/img-[a-f0-9]{32}\.(svg|png)", path):
                image = svc.media.media_dir / path.rsplit("/", 1)[1]
                if not image.exists():
                    raise ContentError("IMAGE_MISSING", "图片文件不存在。", 404)
                binary(handler, image.read_bytes(), "image/png" if image.suffix == ".png" else "image/svg+xml")
                return True
            else:
                match = re.fullmatch(r"/api/content/(asset-[a-f0-9]{32})(?:/(versions|check-payload|export))?", path)
                if not match:
                    raise ContentError("NOT_FOUND", "接口不存在。", 404)
                asset_id, action = match.groups()
                asset = svc.store.get(asset_id)
                if action == "versions":
                    result = [{k: a.get(k) for k in ("version", "parent_version", "updated_at", "last_action")} for a in svc.store.versions(asset_id)]
                elif action == "check-payload":
                    result = svc.check_payload(asset)
                elif action == "export":
                    buffer = io.BytesIO()
                    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
                        z.writestr("content.json", json.dumps(asset, ensure_ascii=False, indent=2))
                        z.writestr("fact-check-request.json", json.dumps(svc.check_payload(asset), ensure_ascii=False, indent=2))
                        copy = asset["copy"]
                        z.writestr("copy.txt", "\n\n".join(["审核草稿" if not asset["can_publish"] else "已通过交付检查", copy["title"], copy["body"], copy["cta"], " ".join(copy["hashtags"])]))
                        image_order = []
                        for index, image in enumerate(asset["images"]):
                            name, raw = svc.media.export_image(image)
                            # Preserve legacy package names; fixed materials carry explicit order.
                            if image.get("render_method") == "pre_generated":
                                name = f"{index + 1:02d}-" + name
                            z.writestr(name, raw)
                            image_order.append(name)
                        z.writestr("image-order.json", json.dumps(image_order, ensure_ascii=False, indent=2))
                        z.writestr("README.txt", "图文交付包：含实际选中图片、结构化成果、A核查请求及来源。预生成素材仍需核验外观与图片内文字，不代表视觉核验通过。\n" + "\n".join(asset["publish_blockers"]))
                    binary(handler, buffer.getvalue(), "application/zip", asset_id + "-review.zip")
                    return True
                else:
                    result = asset
        elif handler.command == "POST":
            payload = body(handler)
            if path == '/api/content/references':
                result, code = register_reference(svc.media, payload), 201
            elif path == "/api/content/from-handoff":
                from .a_bridge import from_handoff
                result, code = svc.start(from_handoff(payload)), 202
                result = {k: v for k, v in result.items() if k not in ("key", "fingerprint")}
            elif path in ("/api/content/generate", "/api/content/regenerate"):
                result, code = svc.start(payload, path.endswith("regenerate")), 202
                result = {k: v for k, v in result.items() if k not in ("key", "fingerprint")}
            elif path == "/api/content/validate":
                result = svc.validate(payload.get("asset_id", ""), payload)
            elif path in ("/api/content/save", "/api/content/restore"):
                result = svc.mutate(payload.get("asset_id", ""), payload, path.rsplit("/", 1)[1])
            else:
                raise ContentError("NOT_FOUND", "接口不存在。", 404)
        elif handler.command in ("PATCH", "DELETE"):
            match = re.fullmatch(r"/api/content/(asset-[a-f0-9]{32})", path)
            if not match:
                raise ContentError("NOT_FOUND", "接口不存在。", 404)
            payload = body(handler)
            result = svc.mutate(match[1], payload) if handler.command == "PATCH" else svc.delete(match[1], payload)
        else:
            raise ContentError("METHOD_NOT_ALLOWED", "不支持该方法。", 405)
        handler._json(code, {"success": True, "data": result, "error": None})
    except ContentError as exc:
        handler._json(exc.status, {"success": False, "data": None, "error": {"code": exc.code, "message": exc.message}})
    except Exception:
        handler._json(500, {"success": False, "data": None, "error": {"code": "CONTENT_ERROR", "message": "成果服务未完成请求，原稿已保留。"}})
    return True
