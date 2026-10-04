"""业务 API 共用 HTTP 传输层；具体端点定义在各自的 *_api.py 模块。"""

from __future__ import annotations

import json
import math
import os
import re
import socket
import threading
from collections.abc import Mapping
from decimal import Decimal
from http.cookiejar import CookieJar
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import (
    HTTPCookieProcessor,
    HTTPRedirectHandler,
    Request as UrlRequest,
    build_opener,
)

from .pojo import ApiRequest, ApiResponse, QueryValue


DEFAULT_API_BASE_URL = "http://127.0.0.1:8000/api/v1"
API_BASE_URL_ENV = "BUSINESS_API_BASE_URL"
DEFAULT_TIMEOUT_SECONDS = 5.0
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class BusinessApiException(Exception):
    """业务 API 客户端异常的基类。"""


class BusinessApiHttpError(BusinessApiException):
    """服务端返回 HTTP 错误时保留状态码和业务错误码。"""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(f"Business API returned {status_code} ({code}): {message}")


class BusinessApiConnectionError(BusinessApiException):
    """业务 API 无法连接或请求超时。"""


class BusinessApiProtocolError(BusinessApiException):
    """业务 API 返回了不符合 JSON 协议的响应。"""


class _NoRedirectHandler(HTTPRedirectHandler):
    """阻止重定向转发会话及 CSRF 请求头。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def validate_idempotency_key(value: str) -> None:
    """校验业务 API 约定的幂等键格式。"""
    if not value or len(value) > 100 or re.fullmatch(r"[A-Za-z0-9._:-]+", value) is None:
        raise ValueError(
            "idempotency_key must be 1-100 characters using letters, numbers, ., _, :, or -"
        )


class BusinessApiTransport:
    """维护单个业务身份的 HTTP 会话、Cookie、CSRF token 和超时。"""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        configured_url = base_url or os.environ.get(API_BASE_URL_ENV) or DEFAULT_API_BASE_URL
        self._base_url = self._validate_base_url(configured_url)
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be a finite number greater than zero")
        self._timeout_seconds = float(timeout_seconds)
        self._cookie_jar = CookieJar()
        self._opener = build_opener(
            _NoRedirectHandler(), HTTPCookieProcessor(self._cookie_jar)
        )
        self._csrf_token: str | None = None
        self._session_lock = threading.RLock()

    @staticmethod
    def _validate_base_url(value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("base_url must be a string")
        try:
            parsed = urlsplit(value.strip())
            parsed.port  # Force validation of malformed ports.
        except ValueError as error:
            raise ValueError("base_url must be a valid HTTP(S) URL") from error
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("base_url must be an HTTP(S) API root without credentials or query")

        path = parsed.path.rstrip("/")
        if not path:
            path = "/api/v1"
        elif not path.endswith("/api/v1"):
            raise ValueError("base_url path must end with /api/v1")
        return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))

    def send(self, request: ApiRequest[Any]) -> ApiResponse[Any]:
        """发送请求并按需附加 CSRF 与幂等请求头。"""
        with self._session_lock:
            return self._send_locked(request)

    def _send_locked(self, request: ApiRequest[Any]) -> ApiResponse[Any]:
        if request.idempotency_key is not None:
            validate_idempotency_key(request.idempotency_key)

        headers = {
            "Accept": "application/json",
            "User-Agent": "agent-lab-business-api/1.0",
        }
        headers.update(request.headers)

        if request.body is not None:
            headers.setdefault("Content-Type", "application/json; charset=utf-8")
            payload = json.dumps(
                request.body,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
                default=self._json_default,
            ).encode("utf-8")
        else:
            payload = None

        if request.requires_csrf:
            if not self._csrf_token:
                self._refresh_csrf_locked()
            assert self._csrf_token is not None
            headers["X-CSRFToken"] = self._csrf_token

        if request.idempotency_key is not None:
            headers["Idempotency-Key"] = request.idempotency_key

        url = f"{self._base_url}/{request.path.lstrip('/')}"
        if request.query:
            url = f"{url}?{urlencode(self._query_parameters(request.query))}"

        outgoing = UrlRequest(url, data=payload, headers=headers, method=request.method)
        try:
            response = self._open(outgoing)
        except BusinessApiHttpError as error:
            if error.code == "csrf_failed":
                self._csrf_token = None
            raise
        self._update_session_tokens(request, response.data)
        return response

    def _open(self, request: UrlRequest) -> ApiResponse[Any]:
        try:
            with self._opener.open(request, timeout=self._timeout_seconds) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise BusinessApiProtocolError("Business API response exceeded size limit")
                data = self._decode_json(body)
                return ApiResponse(
                    status_code=response.status,
                    headers=self._safe_response_headers(response.headers),
                    data=data,
                )
        except HTTPError as error:
            try:
                body = error.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise BusinessApiProtocolError(
                        "Business API error response exceeded size limit"
                    )
                self._raise_http_error(error.code, body)
            finally:
                error.close()
        except (URLError, TimeoutError, socket.timeout, OSError) as error:
            raise BusinessApiConnectionError("Unable to reach the business API") from error
        raise AssertionError("HTTP error handling should always raise")

    @staticmethod
    def _decode_json(body: bytes) -> Any:
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise BusinessApiProtocolError("Business API returned invalid JSON") from error

    @staticmethod
    def _safe_response_headers(headers: Any) -> dict[str, str]:
        # Cookie values remain in CookieJar and are intentionally not exposed.
        return {
            name.lower(): value
            for name, value in headers.items()
            if name.lower() not in {"set-cookie", "set-cookie2"}
        }

    @staticmethod
    def _raise_http_error(status_code: int, body: bytes) -> None:
        code = "http_error"
        message = f"Business API returned HTTP {status_code}"
        if body:
            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                payload = None
            if isinstance(payload, dict):
                error = payload.get("error")
                if isinstance(error, dict):
                    if isinstance(error.get("code"), str):
                        code = error["code"]
                    if isinstance(error.get("message"), str):
                        message = error["message"]
        raise BusinessApiHttpError(status_code, code, message)

    def _refresh_csrf_locked(self) -> ApiResponse[Any]:
        response = self._open(
            UrlRequest(f"{self._base_url}/auth/csrf", method="GET")
        )
        token = (
            response.data.get("csrf_token")
            if isinstance(response.data, dict)
            else None
        )
        if not isinstance(token, str) or not token:
            raise BusinessApiProtocolError("CSRF response did not contain csrf_token")
        self._csrf_token = token
        return response

    def _update_session_tokens(self, request: ApiRequest[Any], data: Any) -> None:
        if request.method == "POST" and request.path.strip("/") == "auth/login":
            token = data.get("csrf_token") if isinstance(data, dict) else None
            self._csrf_token = token if isinstance(token, str) and token else None
        elif request.method == "POST" and request.path.strip("/") == "auth/logout":
            self._csrf_token = None

    @staticmethod
    def _json_default(value: Any) -> str:
        # Decimal price fields are sent as strings per the API contract.
        if isinstance(value, Decimal):
            return str(value)
        raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")

    @staticmethod
    def _query_parameters(query: Mapping[str, QueryValue]) -> dict[str, QueryValue]:
        """拒绝 bool 等容易误传的分页和筛选参数类型。"""
        parameters: dict[str, str | int] = {}
        for key, value in query.items():
            if not isinstance(key, str):
                raise TypeError("query parameter names must be strings")
            if isinstance(value, bool) or not isinstance(value, (str, int)):
                raise TypeError(f"query parameter {key!r} must be a string or integer")
            parameters[key] = value
        return parameters

    def clear_session(self) -> None:
        """清除当前实例内的会话 Cookie 和 CSRF token。"""
        with self._session_lock:
            self._cookie_jar.clear()
            self._csrf_token = None

    def get_csrf(self) -> ApiResponse[Any]:
        """获取新 CSRF token，并保存到当前会话。"""
        with self._session_lock:
            return self._refresh_csrf_locked()
