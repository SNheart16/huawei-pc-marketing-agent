"""Small JSON-only LLM client using explicit project environment variables.

Only LLM_API_KEY, LLM_BASE_URL, LLM_MODEL and optional LLM_API_TYPE are read.
No desktop application or Codex credentials are accessed, and failed requests
never fall back to simulated content.
"""

import json
import os
import re
import socket
from http.client import HTTPException
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class LLMClientError(RuntimeError):
    """A safe error that never includes response bodies or configuration values."""

    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class _InvalidJSON(ValueError):
    pass


def _reject_json_constant(value):
    raise ValueError("Non-standard JSON numeric constant")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # In particular, never resend Authorization to a redirected host.
        return None


class LLMClient:
    """Request a JSON object through Chat Completions or Responses.

    ``LLM_API_TYPE`` defaults to ``chat_completions`` and also accepts
    ``responses``. ``LLM_BASE_URL`` may be a provider root or end in ``/v1``.
    Only invalid JSON output is retried, once; HTTP failures are never retried.
    """

    _MAX_RESPONSE_BYTES = 4 * 1024 * 1024

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        api_type: Optional[str] = None,
        timeout: float = 45.0,
    ) -> None:
        self._api_key = os.environ.get("LLM_API_KEY", "") if api_key is None else api_key
        configured_base = os.environ.get("LLM_BASE_URL", "") if base_url is None else base_url
        self._model = os.environ.get("LLM_MODEL", "") if model is None else model
        configured_type = os.environ.get("LLM_API_TYPE", "chat_completions") if api_type is None else api_type
        for name, value in (
            ("LLM_API_KEY", self._api_key),
            ("LLM_BASE_URL", configured_base),
            ("LLM_MODEL", self._model),
        ):
            if not isinstance(value, str) or not value.strip():
                raise LLMClientError(f"Missing environment configuration: {name}")
        if any(character in self._api_key for character in ("\r", "\n")):
            raise LLMClientError("Invalid LLM_API_KEY configuration")
        if not isinstance(configured_type, str):
            raise LLMClientError("LLM_API_TYPE must be chat_completions or responses")
        self.api_type = configured_type.strip().lower()
        if self.api_type not in {"chat_completions", "responses"}:
            raise LLMClientError("LLM_API_TYPE must be chat_completions or responses")
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        self.timeout = float(timeout)
        self._endpoint = self._endpoint_url(configured_base)
        self._opener = build_opener(_NoRedirect())

    def _endpoint_url(self, base_url: str) -> str:
        try:
            parsed = urlsplit(base_url.strip())
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
                or not base_url.isascii()
                or any(ord(character) <= 32 or ord(character) == 127 or character == "\\" for character in base_url)
            ):
                raise ValueError
            # Validate a malformed/non-numeric port before any request occurs.
            parsed.port
        except ValueError:
            raise LLMClientError("LLM_BASE_URL must be an HTTPS base URL without credentials or query parameters") from None
        path = parsed.path.rstrip("/")
        for suffix in ("/chat/completions", "/responses"):
            if path.endswith(suffix):
                path = path[:-len(suffix)]
                break
        if not path.endswith("/v1"):
            path += "/v1"
        path += "/responses" if self.api_type == "responses" else "/chat/completions"
        return urlunsplit(("https", parsed.netloc, path, "", ""))

    def generate_json(self, system_prompt: str, payload: dict) -> dict:
        """Generate a JSON object; allow at most one JSON-format retry."""
        if not isinstance(system_prompt, str) or not system_prompt.strip():
            raise ValueError("system_prompt must be a non-empty string")
        if not isinstance(payload, dict):
            raise TypeError("payload must be a dict")
        try:
            user_text = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError):
            raise ValueError("payload must contain JSON-serializable values") from None
        for attempt in range(2):
            instructions = system_prompt + "\nReturn a JSON object."
            if attempt:
                instructions += "\nReturn valid JSON only, without Markdown fences."
            try:
                response = self._request(self._request_body(instructions, user_text))
                text = self._response_text(response)
                return self._parse_json_object(text)
            except _InvalidJSON:
                if attempt:
                    raise LLMClientError("The model did not return a valid JSON object after one format retry") from None
        raise LLMClientError("The model did not return a JSON object")

    def _request_body(self, instructions: str, user_text: str) -> dict:
        if self.api_type == "responses":
            return {
                "model": self._model,
                "instructions": instructions,
                "input": user_text,
                "text": {"format": {"type": "json_object"}},
            }
        return {
            "model": self._model,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": user_text},
            ],
            "response_format": {"type": "json_object"},
        }

    def _request(self, body: dict) -> dict:
        request = Request(
            self._endpoint,
            data=json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8"),
            headers={
                "Authorization": "Bearer " + self._api_key,
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json",
                "User-Agent": "huawei-marketing-agent/0.4",
            },
            method="POST",
        )
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                raw = response.read(self._MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            code = exc.code if isinstance(exc.code, int) else None
            # Closing without reading also prevents delayed ResourceWarnings
            # from displaying an HTTP error's unsanitized server message.
            exc.close()
            suffix = f" (HTTP {code})" if code is not None else ""
            raise LLMClientError("LLM request failed" + suffix + "; response details were withheld", code) from None
        except (TimeoutError, socket.timeout):
            raise LLMClientError("LLM request timed out") from None
        except URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise LLMClientError("LLM request timed out") from None
            raise LLMClientError("Unable to reach the configured LLM service; connection details were withheld") from None
        except OSError:
            raise LLMClientError("LLM connection failed; connection details were withheld") from None
        except (HTTPException, ValueError, UnicodeError):
            raise LLMClientError("LLM request could not be sent safely; configuration details were withheld") from None
        if len(raw) > self._MAX_RESPONSE_BYTES:
            raise LLMClientError("LLM response exceeded the permitted size")
        try:
            parsed = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise _InvalidJSON from None
        if not isinstance(parsed, dict):
            raise LLMClientError("LLM returned an unexpected response structure")
        return parsed

    def _response_text(self, response: dict) -> str:
        if self.api_type == "chat_completions":
            choices = response.get("choices")
            if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                raise LLMClientError("LLM response did not include generated content")
            message = choices[0].get("message")
            if not isinstance(message, dict):
                raise LLMClientError("LLM response did not include generated content")
            if message.get("refusal"):
                raise LLMClientError("The model declined the request")
            content = message.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                texts = [part["text"] for part in content if isinstance(part, dict) and isinstance(part.get("text"), str)]
                if texts:
                    return "".join(texts)
        else:
            texts = []
            output = response.get("output", [])
            if isinstance(output, list):
                for item in output:
                    if not isinstance(item, dict) or item.get("type") != "message":
                        continue
                    content = item.get("content", [])
                    if not isinstance(content, list):
                        continue
                    for part in content:
                        if not isinstance(part, dict):
                            continue
                        if part.get("type") == "refusal":
                            raise LLMClientError("The model declined the request")
                        if part.get("type") == "output_text" and isinstance(part.get("text"), str):
                            texts.append(part["text"])
            if texts:
                return "".join(texts)
            if isinstance(response.get("output_text"), str):
                return response["output_text"]
        raise LLMClientError("LLM response did not include generated text")

    @staticmethod
    def _parse_json_object(text: str) -> dict:
        cleaned = text.strip()
        fenced = re.fullmatch(r"```(?:json)?\s*\n?(.*?)\n?```", cleaned, flags=re.IGNORECASE | re.DOTALL)
        if fenced:
            cleaned = fenced.group(1).strip()
        try:
            parsed = json.loads(cleaned, parse_constant=_reject_json_constant)
        except (json.JSONDecodeError, ValueError):
            raise _InvalidJSON from None
        if not isinstance(parsed, dict):
            raise _InvalidJSON
        return parsed
