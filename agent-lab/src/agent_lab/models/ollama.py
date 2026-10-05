"""使用 Python 标准库调用 Ollama 的聊天 API。"""

from __future__ import annotations

from ..runtime.tracing import span

import json
import math
import socket
from collections.abc import Mapping, Sequence
from typing import Any, NotRequired, TypedDict, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request as UrlRequest, build_opener


DEFAULT_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen3.5:9b"
DEFAULT_TIMEOUT_SECONDS = 120.0
MAX_RESPONSE_BYTES = 32 * 1024 * 1024


class OllamaError(Exception):
    """Ollama 客户端异常的基类。"""


class OllamaConnectionError(OllamaError):
    """Ollama 无法连接或请求超时。"""


class OllamaHttpError(OllamaError):
    """Ollama 返回非成功 HTTP 状态。"""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"Ollama API returned {status_code}: {message}")


class OllamaProtocolError(OllamaError):
    """Ollama 响应不是客户端预期的 JSON 聊天响应。"""


class OllamaToolCallFunction(TypedDict):
    """模型返回的单个函数调用。"""

    name: str
    arguments: dict[str, Any]


class OllamaToolCall(TypedDict):
    """Ollama assistant 消息中的工具调用。"""

    function: OllamaToolCallFunction
    index: NotRequired[int]


class OllamaMessage(TypedDict, total=False):
    """Ollama 返回的 assistant 消息。"""

    role: str
    content: str
    thinking: str
    tool_calls: list[OllamaToolCall]


class OllamaChatResponse(TypedDict):
    """非流式 /api/chat 响应；其他 Ollama 元数据也会原样保留。"""

    model: str
    message: OllamaMessage
    done: bool
    created_at: NotRequired[str]
    done_reason: NotRequired[str]
    total_duration: NotRequired[int]
    load_duration: NotRequired[int]
    prompt_eval_count: NotRequired[int]
    prompt_eval_duration: NotRequired[int]
    eval_count: NotRequired[int]
    eval_duration: NotRequired[int]


class _NoRedirectHandler(HTTPRedirectHandler):
    """将意外重定向作为 HTTP 错误返回，不跟随到其他地址。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


class OllamaClient:
    """访问一个 Ollama 实例并使用固定模型生成聊天响应。

    配置由构造参数传入，不读取环境变量。默认使用本地地址与 qwen3.5:9b。
    调用使用非流式响应，
    以便一次得到完整消息和可能的工具调用。
    """

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        context_tokens: int | None = None,
    ) -> None:
        configured_url = DEFAULT_BASE_URL if base_url is None else base_url
        configured_model = DEFAULT_MODEL if model is None else model
        self._base_url = self.validate_base_url(configured_url)
        self._model = self.validate_model(configured_model)
        self._timeout_seconds = self.validate_timeout(timeout_seconds)
        if context_tokens is not None and (type(context_tokens) is not int or context_tokens <= 0):
            raise ValueError("context_tokens must be a positive integer")
        self._context_tokens = context_tokens
        self._opener = build_opener(_NoRedirectHandler())

    @property
    def model(self) -> str:
        """此客户端默认使用的模型名。"""
        return self._model

    def chat_with_tool_definitions(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        tool_definitions: Sequence[Mapping[str, Any]],
        timeout_seconds: float | None = None,
    ) -> OllamaChatResponse:
        """接收项目内部工具描述，并转换为 Ollama 函数工具格式后聊天。"""
        tools = self._format_tool_definitions(tool_definitions)
        return self.chat(messages, tools=tools, timeout_seconds=timeout_seconds)

    def chat(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
        options: Mapping[str, Any] | None = None,
        format: str | Mapping[str, Any] | None = None,
        think: bool | str | None = None,
        keep_alive: str | int | None = None,
        timeout_seconds: float | None = None,
    ) -> OllamaChatResponse:
        """发送聊天历史并返回完整 assistant 响应。

        ``tools`` 使用 Ollama 的函数工具格式。此方法只与模型通信，不执行模型
        请求的工具；工具执行与确认由调用方的运行时负责。
        ``timeout_seconds`` 可为单次请求覆盖构造器默认超时，不改变后续请求。
        """
        request_messages = self._mapping_sequence(messages, "messages", allow_empty=False)
        request_timeout = (
            self._timeout_seconds
            if timeout_seconds is None
            else self.validate_timeout(timeout_seconds)
        )
        for index, message in enumerate(request_messages):
            role = message.get("role")
            if not isinstance(role, str) or not role.strip():
                raise ValueError(f"messages[{index}].role must be a non-empty string")
            if not isinstance(message.get("content"), str):
                raise ValueError(f"messages[{index}].content must be a string")
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": request_messages,
            "stream": False,
        }
        if tools is not None:
            payload["tools"] = self._mapping_sequence(tools, "tools", allow_empty=True)
        if self._context_tokens is not None:
            payload["options"] = {"num_ctx": self._context_tokens}
        if options is not None:
            if not isinstance(options, Mapping):
                raise TypeError("options must be a mapping")
            payload["options"] = {**payload.get("options", {}), **options}
        if format is not None:
            if not isinstance(format, (str, Mapping)):
                raise TypeError("format must be a string or mapping")
            if isinstance(format, str) and not format.strip():
                raise ValueError("format must not be empty")
            payload["format"] = dict(format) if isinstance(format, Mapping) else format
        if think is not None:
            if not isinstance(think, (bool, str)):
                raise TypeError("think must be a boolean or string")
            payload["think"] = think
        if keep_alive is not None:
            if isinstance(keep_alive, bool) or not isinstance(keep_alive, (str, int)):
                raise TypeError("keep_alive must be a string or integer")
            if isinstance(keep_alive, str) and not keep_alive.strip():
                raise ValueError("keep_alive must not be empty")
            if isinstance(keep_alive, int) and keep_alive < 0:
                raise ValueError("keep_alive must not be negative")
            payload["keep_alive"] = keep_alive

        try:
            body = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise ValueError("chat request must contain JSON-compatible values") from error

        request = UrlRequest(
            f"{self._base_url}/api/chat",
            data=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": "agent-lab-ollama/1.0",
            },
            method="POST",
        )
        with span("llm", payload=payload, timeout_seconds=request_timeout) as done:
            response_data = self._open(request, timeout_seconds=request_timeout)
            done(response_data)
            return self._validate_response(response_data)

    @staticmethod
    def validate_base_url(value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("base_url must be a string")
        try:
            parsed = urlsplit(value.strip())
            parsed.port  # Validate malformed ports early.
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
            raise ValueError("base_url must be an HTTP(S) URL without credentials or query")
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))

    @staticmethod
    def validate_model(value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("model must be a non-empty string")
        return value.strip()

    @staticmethod
    def validate_timeout(value: float) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("timeout_seconds must be a finite number greater than zero")
        try:
            timeout = float(value)
        except (OverflowError, ValueError) as error:
            raise ValueError("timeout_seconds must be a finite number greater than zero") from error
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout_seconds must be a finite number greater than zero")
        return timeout

    @staticmethod
    def _mapping_sequence(
        value: Sequence[Mapping[str, Any]], name: str, *, allow_empty: bool
    ) -> list[dict[str, Any]]:
        if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
            raise TypeError(f"{name} must be a sequence of mappings")
        if not value and not allow_empty:
            raise ValueError(f"{name} must not be empty")
        result: list[dict[str, Any]] = []
        for index, item in enumerate(value):
            if not isinstance(item, Mapping):
                raise TypeError(f"{name}[{index}] must be a mapping")
            result.append(dict(item))
        return result

    @staticmethod
    def _format_tool_definitions(
        definitions: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        """将 ToolRegistry 描述转换为 Ollama /api/chat 所需的工具对象。"""
        source = OllamaClient._mapping_sequence(definitions, "tool_definitions", allow_empty=True)
        formatted: list[dict[str, Any]] = []
        names: set[str] = set()
        for index, definition in enumerate(source):
            tool_id = definition.get("tool_id")
            description = definition.get("description")
            parameters = definition.get("parameters")
            if not isinstance(tool_id, str) or not tool_id.strip():
                raise ValueError(f"tool_definitions[{index}].tool_id must be a non-empty string")
            if tool_id in names:
                raise ValueError(f"tool_definitions contains duplicate tool_id: {tool_id}")
            if not isinstance(description, str) or not description.strip():
                raise ValueError(
                    f"tool_definitions[{index}].description must be a non-empty string"
                )
            if not isinstance(parameters, Mapping):
                raise ValueError(f"tool_definitions[{index}].parameters must be a mapping")
            names.add(tool_id)
            formatted.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool_id,
                        "description": description,
                        "parameters": dict(parameters),
                    },
                }
            )
        return formatted

    def _open(self, request: UrlRequest, *, timeout_seconds: float | None = None) -> Any:
        timeout = self._timeout_seconds if timeout_seconds is None else timeout_seconds
        try:
            with self._opener.open(request, timeout=timeout) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise OllamaProtocolError("Ollama response exceeded the size limit")
                return self._decode_json(body)
        except HTTPError as error:
            try:
                body = error.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise OllamaProtocolError("Ollama error response exceeded the size limit")
                message = self._http_error_message(error.code, body)
            except (TimeoutError, socket.timeout, OSError) as read_error:
                raise OllamaConnectionError(
                    "Unable to read the Ollama error response"
                ) from read_error
            finally:
                error.close()
            raise OllamaHttpError(error.code, message) from error
        except (URLError, TimeoutError, socket.timeout, OSError) as error:
            raise OllamaConnectionError("Unable to reach Ollama or request timed out") from error

    @staticmethod
    def _decode_json(body: bytes) -> Any:
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise OllamaProtocolError("Ollama returned invalid JSON") from error

    @staticmethod
    def _http_error_message(status_code: int, body: bytes) -> str:
        default = f"Ollama API returned HTTP {status_code}"
        if not body:
            return default
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return default
        message = payload.get("error") if isinstance(payload, dict) else None
        return message if isinstance(message, str) and message else default

    @staticmethod
    def _validate_response(value: Any) -> OllamaChatResponse:
        if not isinstance(value, dict):
            raise OllamaProtocolError("Ollama response must be a JSON object")
        model = value.get("model")
        message = value.get("message")
        if not isinstance(model, str) or not model:
            raise OllamaProtocolError("Ollama response is missing model")
        if value.get("done") is not True:
            raise OllamaProtocolError("Ollama returned an incomplete chat response")
        if not isinstance(message, dict):
            raise OllamaProtocolError("Ollama response is missing message")
        if message.get("role") != "assistant" or not isinstance(message.get("content"), str):
            raise OllamaProtocolError("Ollama assistant message has an invalid shape")

        tool_calls = message.get("tool_calls", [])
        if not isinstance(tool_calls, list):
            raise OllamaProtocolError("Ollama tool_calls must be a list")
        for index, call in enumerate(tool_calls):
            if not isinstance(call, dict):
                raise OllamaProtocolError(f"Ollama tool_calls[{index}] must be an object")
            function = call.get("function")
            if (
                not isinstance(function, dict)
                or not isinstance(function.get("name"), str)
                or not function["name"]
                or not isinstance(function.get("arguments"), dict)
            ):
                raise OllamaProtocolError(
                    f"Ollama tool_calls[{index}].function has an invalid shape"
                )
        return cast(OllamaChatResponse, value)


__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "DEFAULT_TIMEOUT_SECONDS",
    "MAX_RESPONSE_BYTES",
    "OllamaChatResponse",
    "OllamaClient",
    "OllamaConnectionError",
    "OllamaError",
    "OllamaHttpError",
    "OllamaMessage",
    "OllamaProtocolError",
    "OllamaToolCall",
    "OllamaToolCallFunction",
]
