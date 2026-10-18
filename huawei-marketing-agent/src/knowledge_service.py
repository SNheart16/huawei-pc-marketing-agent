"""Select exactly one read-only knowledge source for each retrieval request.

``KNOWLEDGE_SOURCE_MODE`` accepts ``ima``, ``local``, and ``auto``.  An unset
variable defaults to ``ima``; local files are never enabled implicitly.
"""

import os
from typing import Any, Optional

from .ima_client import ImaClient, ImaClientError


DEFAULT_KB_NAME = "任德耀新建华为PC知识库"


class KnowledgeService:
    """Route retrievals without combining online and local evidence.

    Clients may be injected for offline tests.  Otherwise they are constructed
    only when their source is selected, so local mode never checks ima keys.
    Automatic fallback relies on structured error codes/kinds, never warning
    text, product conflicts, missing credentials, or ordinary API failures.
    """

    def __init__(
        self,
        mode: Optional[str] = None,
        ima_client: Any = None,
        local_client: Any = None,
    ) -> None:
        configured_mode = os.environ.get("KNOWLEDGE_SOURCE_MODE", "ima") if mode is None else mode
        if not isinstance(configured_mode, str):
            raise ValueError("KNOWLEDGE_SOURCE_MODE must be ima, local, or auto")
        self.mode = configured_mode.strip().lower()
        if self.mode not in {"ima", "local", "auto"}:
            raise ValueError("KNOWLEDGE_SOURCE_MODE must be ima, local, or auto")
        self._ima_client = ima_client
        self._local_client = local_client

    def retrieve_product_documents(
        self,
        product_query: str,
        kb_name: str = DEFAULT_KB_NAME,
    ) -> dict:
        """Return one source's documents and explicit, path-free provenance."""
        if not isinstance(product_query, str) or not product_query.strip():
            raise ValueError("product_query must be a non-empty string")
        if not isinstance(kb_name, str) or not kb_name.strip():
            raise ValueError("kb_name must be a non-empty string")

        if self.mode == "local":
            result = self._local().retrieve_product_documents(product_query, kb_name)
            return self._with_source(result, "local", kb_name)

        try:
            result = self._ima().retrieve_product_documents(product_query, kb_name)
        except ImaClientError as exc:
            reason = self._fallback_reason(exc)
            if self.mode != "auto" or reason is None:
                raise
            return self._retrieve_local_fallback(product_query, kb_name, reason)

        self._validate_result(result)
        reason = self._fallback_reason(result.get("source_error"))
        # An explicit ambiguity or disagreement takes precedence over a later
        # availability error: changing source cannot resolve the user's choice.
        if result.get("status") in {"conflict", "needs_input"}:
            return self._with_source(result, "ima", kb_name, reason)
        if self.mode == "auto" and reason is not None:
            return self._retrieve_local_fallback(product_query, kb_name, reason)
        return self._with_source(result, "ima", kb_name, reason)

    def _ima(self) -> Any:
        if self._ima_client is None:
            self._ima_client = ImaClient()
        return self._ima_client

    def _local(self) -> Any:
        if self._local_client is None:
            from .local_kb_client import LocalKbClient

            self._local_client = LocalKbClient()
        return self._local_client

    def _retrieve_local_fallback(self, query: str, kb_name: str, reason: str) -> dict:
        # The online result is intentionally discarded in full, even when it
        # contained some successfully read documents before the source failed.
        result = self._local().retrieve_product_documents(query, kb_name)
        return self._with_source(result, "local", kb_name, reason)

    @staticmethod
    def _fallback_reason(error: Any) -> Optional[str]:
        if isinstance(error, dict):
            code, kind = error.get("code"), error.get("kind")
        elif isinstance(error, ImaClientError):
            code, kind = getattr(error, "code", None), getattr(error, "kind", None)
        else:
            return None
        if code == 220021 or kind == "quota_limited":
            return "quota_limited"
        if kind in {"unavailable", "timeout"}:
            return "unavailable"
        return None

    @staticmethod
    def _validate_result(result: Any) -> None:
        if not isinstance(result, dict):
            raise TypeError("The knowledge client must return a dict")

    @classmethod
    def _with_source(
        cls,
        result: dict,
        mode: str,
        kb_name: str,
        source_status: Optional[str] = None,
    ) -> dict:
        cls._validate_result(result)
        status = source_status or "ok"
        existing_source = result.get("knowledge_source")
        local_unavailable = (
            mode == "local"
            and isinstance(existing_source, dict)
            and existing_source.get("status") == "unavailable"
        )
        if local_unavailable:
            status = "unavailable"
            if source_status is not None:
                message = "ima 无法完成本次读取，本地只读副本也不可用；本次未混合资料。"
            else:
                message = "本地知识库只读副本不可用；请检查本地配置和可读性。"
        elif mode == "local" and status == "quota_limited":
            message = "ima 当日资料读取额度已用尽；本次仅使用本地只读副本。"
        elif mode == "local" and status == "unavailable":
            message = "ima 暂时不可用或请求超时；本次仅使用本地只读副本。"
        elif mode == "ima" and status == "quota_limited":
            message = "ima 当日资料读取额度已用尽；本次保留在线来源状态。"
        elif mode == "ima" and status == "unavailable":
            message = "ima 暂时不可用或请求超时；本次保留在线来源状态。"
        elif mode == "local":
            message = "本次仅使用本地知识库只读副本，资料并非实时在线读取。"
        else:
            message = "本次仅使用 ima 在线只读资料。"
        decorated = dict(result)
        decorated["knowledge_source"] = {
            "mode": mode,
            "name": kb_name,
            "live": mode == "ima",
            "status": status,
            "message": message,
        }
        return decorated
