"""本机 HTTP 入口：组装模型、用户会话、循环和执行器，不接收模型角色或权限。"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from collections.abc import Callable, Mapping
from typing import Literal, NotRequired, TypedDict
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import secrets
import threading
import time

from .clients import AuthApi, BusinessApiTransport, BusinessApiHttpError, BusinessApiException
from .config import Settings, load_settings
from .models import OllamaClient, ModelError, Message, ChatModel
from .runtime.executor import ToolExecutor
from .runtime.loop import LoopError, LoopResult, run_loop, resume_loop
from .tools import ALL_TOOLS, ToolRegistry
from .clients import CurrentUserResponse
from .runtime.tracing import configure_logging, emit, span, trace_context, set_context


class RequestError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        self.status, self.code, self.message = status, code, message


@dataclass(frozen=True, slots=True)
class ChatInput:
    conversation_id: str
    request_id: str
    message: str


@dataclass(frozen=True, slots=True)
class ConfirmationInput:
    conversation_id: str
    request_id: str
    confirmation_id: str
    accept: bool


class AgentReply(TypedDict):
    reply: str
    status: Literal["completed", "confirmation_required", "cancelled", "budget_exhausted", "error"]
    implemented: bool
    confirmation_id: NotRequired[str]
    confirmation: NotRequired[Mapping[str, object] | None]


@dataclass(slots=True)
class Conversation:
    transport: BusinessApiTransport
    touched: float = field(default_factory=time.monotonic)
    lock: threading.Lock = field(default_factory=threading.Lock)
    history: tuple[Message, ...] = ()
    pending: LoopResult | None = None
    executor: ToolExecutor | None = None
    registry: ToolRegistry | None = None
    confirmation_id: str | None = None
    task_id: str | None = None
    replies: dict[str, tuple[str, AgentReply]] = field(default_factory=dict)


class AgentApplication:
    def __init__(
        self,
        settings: Settings,
        *,
        model_factory: Callable[[], ChatModel] | None = None,
        transport_factory: Callable[[], BusinessApiTransport] | None = None,
    ) -> None:
        self.settings = settings
        self.model_factory: Callable[[], ChatModel] = model_factory or (
            lambda: OllamaClient(
                settings.model_base_url,
                settings.model_name,
                timeout_seconds=settings.model_timeout_seconds,
                context_tokens=settings.model_context_tokens,
            )
        )
        self.transport_factory: Callable[[], BusinessApiTransport] = transport_factory or (
            lambda: BusinessApiTransport(
                settings.business_api_base_url,
                timeout_seconds=settings.business_api_timeout_seconds,
            )
        )
        self._conversations: dict[str, Conversation] = {}
        self._lock = threading.Lock()

    def _conversation(self, session_key: str | None, conversation_id: str) -> Conversation:
        if not isinstance(session_key, str) or re.fullmatch(r"[a-z0-9]{32}", session_key) is None:
            raise RequestError(401, "unauthenticated", "请先登录业务网站")
        key = hashlib.sha256((session_key + ":" + conversation_id).encode()).hexdigest()
        with self._lock:
            now = time.monotonic()
            for old, state in list(self._conversations.items()):
                if now - state.touched > 1800 and not state.lock.locked():
                    del self._conversations[old]
            if key not in self._conversations:
                if len(self._conversations) >= 64:
                    raise RequestError(503, "busy", "会话已满，请稍后重试")
                transport = self.transport_factory()
                transport.bind_business_session(session_key)
                self._conversations[key] = Conversation(transport)
            state = self._conversations[key]
            state.touched = now
            return state

    def handle(self, route: str, session_key: str | None, data: object) -> AgentReply:
        ids = (
            {key: data.get(key) for key in ("conversation_id", "request_id")}
            if isinstance(data, dict)
            else {}
        )
        with trace_context(
            trace_id=secrets.token_hex(16),
            **ids,
            sensitive_values=(
                session_key,
                data.get("confirmation_id") if isinstance(data, dict) else None,
            ),
        ):
            # 不记录 HTTP 头、会话键或任意额外的客户端字段。
            inputs = (
                {key: data[key] for key in ("message", "accept") if key in data}
                if isinstance(data, dict)
                else {}
            )
            with span("request", route=route, input=inputs) as done:
                result = self._handle(route, session_key, data)
                done(result)
                return result

    @staticmethod
    def _parse_input(route: str, data: object) -> ChatInput | ConfirmationInput:
        if route not in {"/chat", "/confirm"}:
            raise RequestError(404, "not_found", "接口不存在")
        required = {"conversation_id", "request_id"}
        required |= {"message"} if route == "/chat" else {"confirmation_id", "accept"}
        if not isinstance(data, dict) or set(data) != required:
            raise RequestError(400, "invalid_fields", "请求字段缺失或不允许")

        def identifier(value: object) -> str:
            if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value) is None:
                raise RequestError(400, "invalid_input", "会话或请求编号格式错误")
            return value

        conversation_id = identifier(data["conversation_id"])
        request_id = identifier(data["request_id"])
        if route == "/chat":
            message = data["message"]
            if not isinstance(message, str) or not 1 <= len(message.strip()) <= 2000:
                raise RequestError(400, "invalid_input", "消息须为 1～2000 字")
            return ChatInput(conversation_id, request_id, message)
        confirmation_id, accept = data["confirmation_id"], data["accept"]
        if (
            not isinstance(accept, bool)
            or not isinstance(confirmation_id, str)
            or re.fullmatch(r"[A-Za-z0-9_-]{1,100}", confirmation_id) is None
        ):
            raise RequestError(400, "invalid_input", "确认参数格式错误")
        return ConfirmationInput(conversation_id, request_id, confirmation_id, accept)

    def _handle(self, route: str, session_key: str | None, raw_data: object) -> AgentReply:
        data = self._parse_input(route, raw_data)
        state = self._conversation(session_key, data.conversation_id)
        if not state.lock.acquire(blocking=False):
            raise RequestError(409, "busy", "上一条消息仍在处理，请稍候")
        try:
            identity = AuthApi(state.transport).current_user().data
            if (
                not isinstance(identity, dict)
                or not isinstance(identity.get("username"), str)
                or not identity["username"]
                or type(identity.get("is_staff")) is not bool
            ):
                raise RequestError(502, "invalid_identity", "业务服务身份响应异常")
            emit("identity.verified", is_staff=identity["is_staff"])
            request_key = data.request_id
            fingerprint = json.dumps([route, asdict(data)], sort_keys=True, ensure_ascii=False)
            if request_key in state.replies:
                old, reply = state.replies[request_key]
                if old != fingerprint:
                    raise RequestError(409, "request_conflict", "同一请求编号不能修改内容")
                emit("request.replayed")
                return reply
            if len(state.replies) >= 50:
                raise RequestError(
                    409, "conversation_limit", "本轮对话已达上限，请刷新页面开始新对话"
                )
            # 异常后同一请求也不能隐式重复执行；只缓存公开的错误，不缓存凭据。
            try:
                reply = self._turn(state, identity, data)
            except (ModelError, LoopError) as error:
                emit("agent.error", error_type=type(error).__name__)
                reply = {
                    "reply": "模型调用失败或响应异常。若刚确认过写入，请先核实操作记录，不要重复提交。",
                    "status": "error",
                    "implemented": True,
                }
            state.replies[request_key] = (fingerprint, reply)
            return reply
        finally:
            state.touched = time.monotonic()
            state.lock.release()

    def _turn(
        self,
        state: Conversation,
        identity: CurrentUserResponse,
        data: ChatInput | ConfirmationInput,
    ) -> AgentReply:
        if isinstance(data, ChatInput):
            if state.pending is not None:
                raise RequestError(409, "confirmation_pending", "请先确认或取消页面中的待处理操作")
            if len(state.history) > 80:
                raise RequestError(409, "conversation_limit", "对话过长，请刷新页面开始新对话")
            state.task_id = secrets.token_hex(16)
            set_context(task_id=state.task_id)
            registry = ToolRegistry(t for t in ALL_TOOLS if not t.admin or identity["is_staff"])
            executor = ToolExecutor(state.transport, registry, username=identity["username"])
            state.registry, state.executor = registry, executor
            result = run_loop(
                data.message,
                model=self.model_factory(),
                executor=executor,
                registry=registry,
                history=state.history,
                timeout_seconds=self.settings.model_timeout_seconds,
            )
        else:
            if (
                state.pending is None
                or state.confirmation_id is None
                or not secrets.compare_digest(data.confirmation_id, state.confirmation_id)
            ):
                raise RequestError(409, "confirmation_expired", "确认已失效或已处理")
            set_context(task_id=state.task_id)
            emit("confirmation.received", accept=data.accept)
            previous = state.pending
            if not data.accept:
                messages = list(previous.messages)
                for call in previous.pending_calls:
                    messages.append(
                        Message(
                            "tool",
                            tool_result={
                                "call_id": call.call_id,
                                "tool_id": call.tool_id,
                                "status": "error",
                                "result": None,
                                "error": {"code": "user_cancelled", "message": "用户取消操作"},
                            },
                        )
                    )
                messages.append(Message("assistant", "已取消尚未执行的操作。"))
                state.history, state.pending, state.confirmation_id = tuple(messages), None, None
                return {
                    "reply": "已取消尚未执行的操作。",
                    "status": "cancelled",
                    "implemented": True,
                }
            pending_executor, pending_registry = state.executor, state.registry
            if pending_executor is None or pending_registry is None:
                raise RequestError(409, "confirmation_expired", "确认状态不完整，请取消后重新查询")
            try:
                pending_executor.confirm(
                    previous.pending_calls[0].call_id, username=identity["username"]
                )
            except ValueError:
                raise RequestError(
                    409, "confirmation_expired", "确认已过期，请取消后重新查询"
                ) from None
            # 先消耗确认令牌，异常也不能让旧令牌重新触发执行。
            state.pending, state.confirmation_id = None, None
            result = resume_loop(
                previous,
                model=self.model_factory(),
                executor=pending_executor,
                registry=pending_registry,
                timeout_seconds=self.settings.model_timeout_seconds,
            )
        emit(
            "loop.finished",
            status=result.status,
            model_calls=result.model_calls,
            tool_calls=result.tool_calls,
            prompt_version=result.prompt_version,
        )
        if result.status == "confirmation_required":
            state.pending = result
            state.confirmation_id = secrets.token_urlsafe(24)
            return {
                "reply": "请核对以下操作，点击确认后才会执行。",
                "status": result.status,
                "implemented": True,
                "confirmation_id": state.confirmation_id,
                "confirmation": result.pending_confirmation,
            }
        # 预算耗尽可能有未配对的 tool_calls，不将半截消息交给下一轮模型。
        if result.status == "completed":
            state.history = result.messages
        return {
            "reply": result.reply or "本轮已达到执行上限，请先核实已有结果。",
            "status": result.status,
            "implemented": True,
        }


class Handler(BaseHTTPRequestHandler):
    server: AgentHTTPServer

    def log_message(self, format: str, *args: object) -> None:
        # 默认访问日志含原始 URL；避免意外记录查询参数中的凭据。
        pass

    def respond(self, status: int, data: object) -> None:
        emit("http.response", status_code=status)
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass  # 已执行的结果仍保留，调用方可用原 request_id 查询重放。

    def do_GET(self) -> None:
        if self.path == "/health":
            self.respond(200, {"status": "ok", "agent_implemented": True})
        else:
            self.respond(404, {"error": {"code": "not_found", "message": "接口不存在"}})

    def do_POST(self) -> None:
        try:
            if self.path not in {"/chat", "/confirm"}:
                raise RequestError(404, "not_found", "接口不存在")
            # 浏览器只访问带 CSRF 保护的网站代理；不直接调用 Agent 端口。
            if self.headers.get("Origin") or self.headers.get("Sec-Fetch-Site"):
                raise RequestError(403, "proxy_required", "请通过业务网站访问")
            if self.headers.get_content_type() != "application/json":
                raise RequestError(415, "invalid_content_type", "请求必须是 JSON")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 16384:
                raise RequestError(400, "invalid_input", "请求长度不合法")
            self.connection.settimeout(10)
            data = json.loads(self.rfile.read(length))
            result = self.server.application.handle(
                self.path, self.headers.get("X-Business-Session"), data
            )
            self.respond(200, result)
        except RequestError as error:
            self.respond(error.status, {"error": {"code": error.code, "message": error.message}})
        except BusinessApiHttpError as error:
            status = 401 if error.status_code in (401, 403) else 502
            self.respond(
                status, {"error": {"code": "business_auth", "message": "请重新登录或检查业务服务"}}
            )
        except BusinessApiException:
            self.respond(
                503, {"error": {"code": "business_unavailable", "message": "业务服务不可用"}}
            )
        except (ValueError, UnicodeDecodeError, TimeoutError):
            self.respond(400, {"error": {"code": "invalid_json", "message": "请求格式错误"}})
        except Exception:
            self.respond(
                500,
                {
                    "error": {
                        "code": "internal_error",
                        "message": "服务异常；若涉及写入请先核实操作记录",
                    }
                },
            )


class AgentHTTPServer(ThreadingHTTPServer):
    """显式持有应用的 HTTP 服务器；创建时必须提供应用实例。"""

    application: AgentApplication

    def __init__(self, address: tuple[str, int], application: AgentApplication) -> None:
        self.application = application
        super().__init__(address, Handler)


def main() -> None:
    settings = load_settings()
    log_path = configure_logging(settings.log_dir)
    server = AgentHTTPServer(("127.0.0.1", settings.agent_port), AgentApplication(settings))
    emit(
        "service.started",
        port=settings.agent_port,
        model=settings.model_name,
        log_file=str(log_path),
    )
    print(f"Agent service: http://127.0.0.1:{settings.agent_port}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        emit("service.stopped")


if __name__ == "__main__":
    main()
