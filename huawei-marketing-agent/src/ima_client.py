"""Read-only client for the official ima_api.cjs knowledge-base interface."""

import json
import os
import re
import socket
import subprocess
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Set
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class _NoRedirect(HTTPRedirectHandler):
    """Do not forward a media access header to a redirected destination."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ImaClientError(RuntimeError):
    """Raised when a read-only ima request cannot be completed safely."""

    def __init__(
        self, message: str, code: Optional[int] = None, kind: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.kind = kind or (
            "quota_limited" if code == 220021 else
            "unavailable" if code == 110010 else None
        )


class ImaClient:
    """Call the project's official ima script for knowledge-base reads only."""

    _READ_ONLY_ENDPOINTS = {
        "openapi/wiki/v1/search_knowledge_base",
        "openapi/wiki/v1/get_knowledge_list",
        "openapi/wiki/v1/search_knowledge",
        "openapi/wiki/v1/get_media_info",
    }
    _REQUIRED_ENV = ("IMA_OPENAPI_CLIENTID", "IMA_OPENAPI_APIKEY")
    _SENSITIVE_KEYS = {
        "authorization",
        "cookie",
        "set_cookie",
        "ima_openapi_clientid",
        "ima_openapi_apikey",
        "clientid",
        "client_id",
        "api_key",
        "apikey",
        "secret_key",
    }

    def __init__(
        self,
        project_root: Optional[Path] = None,
        node_executable: str = "node",
        timeout: float = 30.0,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")

        self.project_root = Path(project_root or Path(__file__).resolve().parents[1]).resolve()
        self.script_path = self.project_root / "ima-skill" / "ima-skill" / "ima_api.cjs"
        self.node_executable = node_executable
        self.timeout = timeout

    def call_api(self, endpoint: str, payload: dict) -> dict:
        """Call one allowlisted read-only endpoint and return its JSON envelope."""
        return self._redact_sensitive_data(self._invoke_api(endpoint, payload))

    def _invoke_api(self, endpoint: str, payload: dict) -> dict:
        """Internal response; access headers stay in memory and never reach callers."""
        normalized_endpoint = endpoint.lstrip("/") if isinstance(endpoint, str) else ""
        if normalized_endpoint not in self._READ_ONLY_ENDPOINTS:
            raise ValueError("Only allowlisted ima knowledge-base read endpoints are supported")
        if not isinstance(payload, dict):
            raise TypeError("payload must be a dict")

        self._check_credentials()
        if not self.script_path.is_file():
            raise ImaClientError("The official ima_api.cjs script was not found at its project-relative path")

        self._reject_sensitive_payload(payload)
        serialized_payload = json.dumps(payload, ensure_ascii=False)
        command = [
            self.node_executable,
            str(self.script_path),
            normalized_endpoint,
            serialized_payload,
        ]

        try:
            completed = subprocess.run(
                command,
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise ImaClientError(
                f"ima request timed out for {normalized_endpoint} after {self.timeout:g} seconds",
                kind="timeout",
            ) from None
        except FileNotFoundError:
            raise ImaClientError("Node.js or the official ima_api.cjs script could not be found") from None
        except OSError:
            raise ImaClientError("Unable to start the official ima API process") from None

        if completed.returncode != 0:
            error_code = self._extract_error_code(completed.stderr)
            detail = f" (ima error code {error_code})" if error_code is not None else ""
            raise ImaClientError(
                f"ima request failed for {normalized_endpoint}{detail}; raw details were withheld",
                code=error_code,
            )

        try:
            response = json.loads(completed.stdout.lstrip("\ufeff"))
        except (TypeError, json.JSONDecodeError):
            raise ImaClientError("ima_api.cjs returned invalid JSON; response details were withheld") from None

        if not isinstance(response, dict):
            raise ImaClientError("ima_api.cjs returned an unexpected response type")

        return response

    def search_knowledge_base(
        self,
        query: str,
        cursor: str = "",
        limit: int = 20,
    ) -> dict:
        """Search knowledge bases by name and return the API data object."""
        if not isinstance(query, str):
            raise TypeError("query must be a str")
        self._validate_limit(limit, 1, 20)
        return self._response_data(
            self.call_api(
                "openapi/wiki/v1/search_knowledge_base",
                {"query": query, "cursor": cursor, "limit": limit},
            ),
            "openapi/wiki/v1/search_knowledge_base",
        )

    def get_knowledge_list(
        self,
        kb_id: str,
        cursor: str = "",
        limit: int = 20,
        folder_id: Optional[str] = None,
    ) -> dict:
        """Return one page of knowledge-base items and pagination metadata."""
        self._validate_identifier(kb_id, "kb_id")
        self._validate_limit(limit, 1, 50)
        payload = {"knowledge_base_id": kb_id, "cursor": cursor, "limit": limit}
        if folder_id is not None:
            self._validate_identifier(folder_id, "folder_id")
            payload["folder_id"] = folder_id
        return self._response_data(
            self.call_api(
                "openapi/wiki/v1/get_knowledge_list",
                payload,
            ),
            "openapi/wiki/v1/get_knowledge_list",
        )

    def search_knowledge(
        self,
        kb_id: str,
        query: str,
        cursor: str = "",
        limit: int = 20,
    ) -> dict:
        """Return a complete server page, including pagination metadata if present.

        The API has no limit parameter. The legacy argument is validated but
        never truncates a page: truncation would lose items before next_cursor.
        """
        self._validate_identifier(kb_id, "kb_id")
        if not isinstance(query, str):
            raise TypeError("query must be a str")
        self._validate_limit(limit, 1, 50)
        data = self._response_data(
            self.call_api(
                "openapi/wiki/v1/search_knowledge",
                {"knowledge_base_id": kb_id, "query": query, "cursor": cursor},
            ),
            "openapi/wiki/v1/search_knowledge",
        )
        return data

    def get_media_info(self, media_id: str) -> dict:
        """Get media access metadata using the documented media_id parameter."""
        self._validate_identifier(media_id, "media_id")
        return self._response_data(
            self.call_api(
                "openapi/wiki/v1/get_media_info",
                {"media_id": media_id},
            ),
            "openapi/wiki/v1/get_media_info",
        )

    def retrieve_product_documents(
        self,
        product_query: str,
        kb_name: str = "任德耀新建华为PC知识库",
    ) -> dict:
        """Read separate source documents; never synthesize specs or merge models.

        candidate_models contains literal model names and their source records.
        A recommended candidate is only a retrieval suggestion, not selection.
        Signed access URLs and headers are used in memory, never returned.
        """
        self._validate_identifier(product_query, "product_query")
        self._validate_identifier(kb_name, "kb_name")
        result = {
            "status": "needs_input", "query": product_query,
            "selected_product_model": None, "candidate_models": [],
            "documents": [], "warnings": [], "missing_information": [],
        }
        warnings = result["warnings"]
        missing = result["missing_information"]
        bases = self._pages(
            lambda cursor: self.search_knowledge_base(kb_name, cursor),
            "info_list", warnings,
        )
        matches = {
            item.get("kb_id") or item.get("id"): item for item in bases
            if (item.get("kb_name") or item.get("name")) == kb_name
            and (item.get("kb_id") or item.get("id"))
        }
        if len(matches) != 1:
            if len(matches) > 1:
                result["status"] = "conflict"
            missing.append("知识库名称未匹配到唯一结果，请确认共享知识库名称。")
            return self._redact_sensitive_data(result)
        kb_id = next(iter(matches))
        hits = self._pages(
            lambda cursor: self.search_knowledge(kb_id, product_query, cursor),
            "info_list", warnings,
        )
        hits = [item for item in hits if not self._is_folder(item) and (
            self._matches_query(product_query, item.get("title", "")) or
            self._matches_query(product_query, item.get("highlight_content", ""))
        )]
        if not hits:
            warnings.append("搜索未返回可确认的产品资料，已使用目录接口逐级回退检索。")
            hits = self._browse_matching(kb_id, product_query, warnings)
        seen = set()
        candidates = {}
        media_reads_stopped = False
        unavailable_documents = 0
        for item in hits:
            media_id = item.get("media_id")
            if not isinstance(media_id, str) or not media_id or media_id in seen:
                continue
            seen.add(media_id)
            document = {
                "media_id": media_id, "product_model": None,
                "document_title": item.get("title") or None,
                "document_type": item.get("media_type"),
                "content": None, "source": None, "media": [],
                "model_evidence": [],
            }
            if media_reads_stopped:
                unavailable_documents += 1
            else:
                try:
                    self._populate_document(document, item, warnings)
                except ImaClientError as exc:
                    unavailable_documents += 1
                    if exc.kind in {"quota_limited", "unavailable", "timeout"}:
                        result.setdefault("source_error", {"code": exc.code, "kind": exc.kind})
                        media_reads_stopped = True
                    detail = f"（错误码 {exc.code}）" if exc.code is not None else ""
                    warnings.append(f"《{item.get('title') or '未命名资料'}》读取失败{detail}；请使用ima客户端查看原文。")
                    # This code was observed with the server message that the
                    # daily media retrieval allowance has been exhausted.
                    if exc.code == 220021:
                        warnings.append("媒体接口返回错误码 220021，已停止本次后续原文读取；请稍后按服务端提示重试。")
                    elif media_reads_stopped:
                        warnings.append("媒体服务暂不可用或请求超时，已停止本次后续原文读取。")
            content = document["content"] or ""
            identities = self._identify_models(product_query, content)
            model = next(iter(identities)) if len(identities) == 1 else None
            evidence = [line for lines in identities.values() for line in lines]
            document["product_model"] = model
            document["model_evidence"] = evidence
            for candidate_model, model_lines in identities.items():
                candidate = candidates.setdefault(candidate_model, {
                    "product_model": candidate_model, "sources": [], "recommended": False,
                })
                candidate["sources"].append({
                    "media_id": media_id, "document_title": document["document_title"],
                    "source": document["source"], "model_evidence": model_lines,
                })
            if len(identities) > 1:
                warnings.append(f"《{document['document_title']}》包含多个明确型号或配置，未绑定为单一型号。")
            if content and not model and document["document_type"] != 9:
                missing.append(f"《{document['document_title']}》缺少可唯一识别的完整型号；保留独立资料。")
            result["documents"].append(document)
        result["candidate_models"] = list(candidates.values())
        if candidates:
            # Prefer a primary product card over a case study; never fill gaps
            # using unrelated material or treat recommendation as confirmation.
            def completeness(candidate):
                ids = {source["media_id"] for source in candidate["sources"]}
                docs = [d for d in result["documents"] if d["media_id"] in ids]
                return max((
                    (2 if "产品类别：" in (d["content"] or "") else 0)
                    + (1 if d["source"] else 0), len(d["content"] or "")
                ) for d in docs)
            max(candidates.values(), key=completeness)["recommended"] = True
        if len(candidates) > 1:
            result["status"] = "conflict"
            warnings.append("资料明确涉及多个型号或版本，未选定型号，未合并正文或配置。")
            missing.append("请指定候选型号；推荐项仅表示资料优先阅读建议，尚未确认为目标型号。")
        elif len(candidates) == 1:
            unknown = any(d["product_model"] is None for d in result["documents"])
            if unknown:
                missing.append("仍有资料或图片无法绑定到唯一型号，请确认其适用版本。")
            if unavailable_documents:
                result["status"] = "partial"
            elif unknown or any("发现卡" in (d["content"] or "") for d in result["documents"]):
                result["status"] = "needs_input"
                missing.append("需确认精确版本及具体销售配置；发现卡或传播案例不能替代完整规格档案。")
            elif warnings or missing:
                result["status"] = "partial"
            else:
                result["status"] = "success"
                result["selected_product_model"] = next(iter(candidates))
        elif unavailable_documents:
            result["status"] = "partial"
            missing.append("部分或全部原文暂未读取，无法据此判断精确型号；请待媒体接口恢复后重试。")
        else:
            missing.append("未取得明确完整型号，请提供具体产品版本或可核验的型号资料。")
        if unavailable_documents and candidates:
            missing.append("部分原文暂未读取，候选型号清单可能不完整；请待媒体接口恢复后重试。")
        if not result["documents"]:
            missing.append("未找到匹配资料；搜索为空不等于无权限。")
        result["warnings"] = list(dict.fromkeys(warnings))
        result["missing_information"] = list(dict.fromkeys(missing))
        return self._redact_sensitive_data(result)

    def _pages(self, fetch, field: str, warnings: list) -> list:
        items, cursors, cursor = [], set(), ""
        for _ in range(100):
            data = fetch(cursor)
            page = data.get(field)
            if not isinstance(page, list):
                warnings.append("接口缺少资料数组，检索结果可能不完整。")
                break
            items.extend(item for item in page if isinstance(item, dict))
            # The live search API sometimes omits both pagination fields.
            if data.get("is_end") is True:
                break
            next_cursor = data.get("next_cursor")
            if not next_cursor and "is_end" not in data:
                warnings.append("接口未返回分页字段，已处理本次响应的全部条目，无法据此保证全库穷尽。")
                break
            if not isinstance(next_cursor, str) or not next_cursor or next_cursor in cursors:
                warnings.append("接口未提供可继续的游标，检索结果可能不完整。")
                break
            cursors.add(next_cursor)
            cursor = next_cursor
        else:
            warnings.append("达到分页读取上限，检索结果可能不完整。")
        return items

    @staticmethod
    def _is_folder(item: dict) -> bool:
        # 99 is observed on real folder entries and verified by browsing them.
        return item.get("media_type") == 99 or bool(item.get("folder_id"))

    @staticmethod
    def _matches_query(query: str, title: str) -> bool:
        normalize = lambda text: re.sub(r"[\W_]+", "", text).casefold()
        return normalize(query) in normalize(title or "")

    def _browse_matching(self, kb_id: str, query: str, warnings: list) -> list:
        pending, visited, matches = [None], set(), []
        while pending and len(visited) < 200:
            folder_id = pending.pop(0)
            if folder_id in visited:
                continue
            visited.add(folder_id)
            items = self._pages(
                lambda cursor: self.get_knowledge_list(kb_id, cursor, 50, folder_id),
                "knowledge_list", warnings,
            )
            for item in items:
                if self._is_folder(item):
                    child_id = item.get("folder_id") or item.get("media_id")
                    if child_id and child_id not in visited:
                        pending.append(child_id)
                elif self._matches_query(query, item.get("title") or item.get("name") or ""):
                    matches.append(item)
        if pending:
            warnings.append("达到目录读取上限，检索结果可能不完整。")
        return matches

    def _populate_document(self, document: dict, item: dict, warnings: list) -> None:
        endpoint = "openapi/wiki/v1/get_media_info"
        data = self._response_data(self._invoke_api(endpoint, {"media_id": item["media_id"]}), endpoint)
        media_type = data.get("media_type", item.get("media_type"))
        document["document_type"] = media_type
        access = data.get("url_info") or {}
        url = access.get("url")
        if not isinstance(url, str) or not url:
            warnings.append(f"《{document['document_title']}》无可读取的原文链接；请使用ima客户端查看原文。")
            return
        if media_type == 9:
            self._read_url(url, access.get("headers") or {}, image=True)
            public_url = self._public_url(url)
            document["media"] = [{
                "name": document["document_title"], "url": public_url,
                "source": public_url, "product_model": None,
                "verification": "mime_and_signature",
            }]
            document["source"] = public_url
            warnings.append(f"《{document['document_title']}》图片类型已验证，精确型号和原始来源尚需确认。")
            if not public_url:
                warnings.append("图片临时访问链接含签名，未在结果中暴露；使用前需重新读取媒体访问信息。")
            return
        if media_type not in (7, 13, 20):
            warnings.append(f"《{document['document_title']}》为当前读取器不支持的正文类型；请使用ima客户端查看原文。")
            return
        content = self._read_url(url, access.get("headers") or {})
        document["content"] = content
        document["source"] = self._source_url(content) or self._public_url(url)
        for name, image_url in re.findall(r'!\[([^\]]*)\]\((https?://[^\s)]+)(?:\s+"[^"]*")?\)', content):
            document["media"].append({
                "name": name or None, "url": self._public_url(image_url),
                "source": document["source"], "product_model": None,
                "verification": "reference_only",
            })
        if document["media"]:
            warnings.append(f"《{document['document_title']}》正文图片仅提取原始引用，未验证链接可访问性或型号。")
        if not document["media"]:
            warnings.append(f"《{document['document_title']}》已读取正文，未返回可提取的 Markdown 图片引用。")

    def _read_url(self, url: str, headers: dict, image: bool = False):
        try:
            parsed = urlsplit(url)
        except ValueError:
            raise ImaClientError("Invalid media access URL; raw details were withheld") from None
        host = parsed.hostname or ""
        if parsed.scheme != "https" or parsed.username or parsed.password or not (
            host == "ima.qq.com" or host.endswith(".myqcloud.com")
        ):
            raise ImaClientError("Media access URL is outside the supported ima/Tencent HTTPS hosts")
        # Only access headers supplied for this URL are used. API credentials
        # are never copied from the environment to the storage request.
        self._reject_sensitive_payload({"url": url})
        for key, value in headers.items():
            if key.casefold().replace("-", "_") in {"ima_openapi_clientid", "ima_openapi_apikey"}:
                raise ImaClientError("Refused to forward API credentials to media storage")
            if any(secret and secret in str(value) for secret in self._configured_secret_values()):
                raise ImaClientError("Refused to forward API credentials to media storage")
        try:
            request = Request(url, headers=headers, method="GET")
            with build_opener(_NoRedirect()).open(request, timeout=self.timeout) as response:
                if response.status != 200:
                    raise ImaClientError("Media origin did not return HTTP 200")
                content_type = response.headers.get_content_type()
                raw = response.read(32 if image else 2_000_001)
            if image:
                signatures = (
                    (content_type == "image/jpeg" and raw.startswith(b"\xff\xd8\xff")),
                    (content_type == "image/png" and raw.startswith(b"\x89PNG\r\n\x1a\n")),
                    (content_type == "image/webp" and raw.startswith(b"RIFF") and raw[8:12] == b"WEBP"),
                )
                if not any(signatures):
                    raise ImaClientError("Image MIME type or signature could not be verified")
                return None
            if len(raw) > 2_000_000:
                raise ImaClientError("Document exceeds the in-memory text size limit")
            return raw.decode("utf-8-sig")
        except HTTPError as exc:
            exc.close()
            raise ImaClientError(
                "Unable to read media content; raw access details were withheld",
                kind="unavailable" if exc.code in (502, 503, 504) else None,
            ) from None
        except (TimeoutError, socket.timeout):
            raise ImaClientError("Media content request timed out", kind="timeout") from None
        except URLError as exc:
            raise ImaClientError(
                "Unable to read media content; raw access details were withheld",
                kind="timeout" if isinstance(exc.reason, TimeoutError) else None,
            ) from None
        except (OSError, ValueError):
            raise ImaClientError("Unable to read media content; raw access details were withheld") from None

    @staticmethod
    def _public_url(url: str) -> Optional[str]:
        try:
            parsed = urlsplit(url)
        except ValueError:
            return None
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            return None
        if any(re.search(r"sign|token|auth|secret|credential|api.?key|client.?id", key, re.I)
               for key, _ in parse_qsl(parsed.query)):
            return None
        return url

    def _source_url(self, content: str) -> Optional[str]:
        source_section = False
        for line in content.splitlines():
            if line.startswith("#"):
                source_section = bool(re.search(r"官方来源|原始来源|来源登记", line))
            if source_section or re.search(r"source_url\s*:|官方页面[：:]|原始URL[：:]", line, re.I):
                match = re.search(r"https?://[^\s<>\]）)]+", line)
                if match:
                    return self._public_url(match.group(0))
        return None

    @staticmethod
    def _identify_models(query: str, content: str) -> dict:
        """Extract literal identity fields/headings, never dates elsewhere in text.

        Deliberately conservative: an article date, bare family name, marketing
        title or narrative reference cannot establish a precise product model.
        """
        phrase = re.escape(query.strip()).replace(r"\ ", r"\s+")
        pattern = re.compile(r"(?:HUAWEI\s+)?" + phrase, re.I)
        models = {}
        for line in content.splitlines():
            explicit = re.match(r"^\s*[-*]?\s*(?:product_model|product_name|产品型号|完整型号|产品名称)\s*[：:]\s*(.+)", line)
            heading = re.match(r"^#\s+(.+)", line)
            if not (explicit or heading):
                continue
            text = (explicit or heading).group(1).strip().strip('"*`')
            if heading:
                text = re.sub(r"^(?:MC-\d+|\d+)\s*[｜|_-]\s*", "", text)
            match = pattern.search(text)
            if not match:
                continue
            tail = text[match.end():].strip()
            year = re.match(r"(?:[（(]\s*)?20\d{2}(?:\s*[款版])?(?:[）)])?", tail)
            qualified_match = re.search(r"20\d{2}|[款版]|\bEdition\b", match.group(0), re.I)
            if not tail and match.start() == 0 and qualified_match:
                model = text
            elif explicit and match.start() == 0 and tail and len(text) <= 120:
                # Explicit identity fields retain all declared configuration
                # qualifiers, including different CPU/memory/storage variants.
                model = text
            elif year:
                remainder = tail[year.end():].strip()
                if re.search(r"\b(?:i[3579]|Ultra\s*\d|\d+\s*(?:GB|TB))\b", remainder, re.I):
                    # A heading with config-like text needs an explicit field
                    # rather than collapsing distinct configurations to a year.
                    continue
                model = text[match.start():match.end()] + " " + year.group(0)
            elif (text[:match.end()].casefold().startswith("huawei ") and match.start() == 0
                  and tail and re.fullmatch(r"[\w\s（）()+.-]+", tail) and len(tail) <= 60
                  and re.search(r"[款版]|\bEdition\b", tail)
                  and not re.search(r"价格卡|参数卡|长页|案例|评测|规格|资料|索引|\b(?:review|is|presents)\b", tail, re.I)):
                model = text
            else:
                continue
            models.setdefault(model, []).append(line)
        return {model: list(dict.fromkeys(evidence)) for model, evidence in models.items()}

    def _check_credentials(self) -> None:
        missing = [name for name in self._REQUIRED_ENV if not os.environ.get(name, "").strip()]
        if missing:
            raise ImaClientError("Missing required environment variable(s): " + ", ".join(missing))

    @staticmethod
    def _validate_identifier(value: str, field_name: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must be a non-empty str")

    @staticmethod
    def _validate_limit(value: int, minimum: int, maximum: int) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise ValueError(f"limit must be an integer from {minimum} to {maximum}")

    @staticmethod
    def _extract_error_code(stderr: str) -> Optional[int]:
        try:
            error = json.loads(stderr)
        except (TypeError, json.JSONDecodeError):
            return None
        code = error.get("code") if isinstance(error, dict) else None
        return code if isinstance(code, int) else None

    def _response_data(self, response: dict, endpoint: str) -> dict:
        code = response.get("code")
        if code not in (0, "0"):
            safe_code = code if re.fullmatch(r"-?\d{1,12}", str(code)) else "unknown"
            raise ImaClientError(
                f"ima API rejected {endpoint} (code {safe_code}); response details were withheld",
                code=int(safe_code) if safe_code != "unknown" else None,
            )
        data = response.get("data")
        if not isinstance(data, dict):
            raise ImaClientError(f"ima API returned no data object for {endpoint}")
        return data

    def _reject_sensitive_payload(self, payload: dict) -> None:
        secret_values = self._configured_secret_values()

        def visit(value: Any) -> bool:
            if isinstance(value, Mapping):
                for key, nested in value.items():
                    normalized_key = str(key).casefold().replace("-", "_")
                    if normalized_key in self._SENSITIVE_KEYS:
                        return True
                    if visit(nested):
                        return True
                return False
            if isinstance(value, (list, tuple)):
                return any(visit(item) for item in value)
            if isinstance(value, str):
                return any(secret and secret in value for secret in secret_values)
            return False

        if visit(payload):
            raise ValueError("payload must not contain credentials or authorization fields")

    def _redact_sensitive_data(self, value: Any) -> Any:
        secret_values = self._configured_secret_values()

        def visit(item: Any) -> Any:
            if isinstance(item, dict):
                sanitized: Dict[str, Any] = {}
                for key, nested in item.items():
                    normalized_key = str(key).casefold().replace("-", "_")
                    if normalized_key in self._SENSITIVE_KEYS:
                        sanitized[key] = "[REDACTED]"
                    else:
                        sanitized[key] = visit(nested)
                return sanitized
            if isinstance(item, list):
                return [visit(element) for element in item]
            if isinstance(item, str):
                for secret in secret_values:
                    if secret:
                        item = item.replace(secret, "[REDACTED]")
                item = re.sub(
                    r"(?im)\b(authorization|(?:set-)?cookie|ima[_-]openapi[_-](?:clientid|apikey))\s*[:=][^\r\n]*",
                    r"\1: [REDACTED]", item,
                )
                item = re.sub(
                    r"https?://[^\s<>\]\"）)]+",
                    lambda match: match.group(0) if self._public_url(match.group(0)) else "[REDACTED_URL]",
                    item,
                )
                return item
            return item

        return visit(value)

    def _configured_secret_values(self) -> Set[str]:
        return {os.environ.get(name, "") for name in self._REQUIRED_ENV}
