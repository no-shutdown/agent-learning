"""单任务、单用户的受控工具执行器；不调用模型、不组织消息历史。"""

from .tracing import traced

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import math
import threading
import time
from uuid import uuid4
from typing import Any

from ..clients import (
    AuthApi,
    BusinessApiTransport,
    ApiResponse,
    BusinessApiConnectionError,
    BusinessApiHttpError,
    BusinessApiProtocolError,
)
from ..tools import InvalidArguments, ToolRegistry
from ..tools.contracts import Tool
from .contracts import json_text


@dataclass
class _Call:
    tool_id: str
    arguments: dict
    fingerprint: str
    operation_key: str | None
    expires_at: float
    approved: bool = False
    result: dict | None = None


class ToolExecutor:
    """每个用户任务创建一个实例，和该用户已登录的 transport 绑定。

    username 必须来自可信登录上下文，不从模型参数读取。确认 API 仅由已验证
    身份的应用代码调用，不能暴露为模型工具。同一任务内相同写入复用原操作。
    状态只保存在内存；不可用于跨重启恢复或跨进程并发执行。
    """

    def __init__(
        self,
        transport: BusinessApiTransport,
        registry: ToolRegistry,
        *,
        username: str,
        max_calls: int = 16,
        confirmation_ttl: float = 300,
    ) -> None:
        if not isinstance(username, str) or not username.strip():
            raise ValueError("需要可信的登录用户名")
        if type(max_calls) is not int or max_calls <= 0:
            raise ValueError("max_calls 必须为正整数")
        self._positive_timeout(confirmation_ttl)
        self._transport = transport
        self._registry = registry
        self._username = username
        self._max_calls = max_calls
        self._ttl = confirmation_ttl
        self._count = 0
        self._calls: dict[str, _Call] = {}
        self._writes: dict[str, _Call] = {}
        self._lock = threading.RLock()

    @traced("confirmation", ("call_id",))
    def confirm(self, call_id: str, *, username: str) -> None:
        """可信 UI 展示 pending 参数并验证用户确认事件后调用；不是模型能力。

        username 是服务端认证身份。调用方不得从用户提交字段或模型文本直接取值。
        execute 会再次向业务服务核实会话身份、管理员资格和确认期限。
        """
        with self._lock:
            call = self._calls.get(call_id)
            if username != self._username:
                raise ValueError("确认身份不匹配")
            if call is None or call.operation_key is None or call.result is not None:
                raise ValueError("不存在可确认的写操作")
            if time.monotonic() >= call.expires_at:
                raise ValueError("确认已过期，请发起新的任务并重新核实参数")
            call.approved = True

    @traced("tool", ("call_id", "tool_id", "arguments", "timeout_seconds"))
    def execute(
        self, *, call_id: str, tool_id: str, arguments: Mapping, timeout_seconds: float
    ) -> dict:
        """检查后至多尝试一次业务操作；重放已完成调用只返回原结果。

        confirmation_required 无副作用。确认后用原 call_id 和原参数再次调用。
        写入超时/异常响应为 unknown，必须查询原 operation_key，不自动重发。
        """
        self._positive_timeout(timeout_seconds)
        if not isinstance(call_id, str) or not call_id.strip() or len(call_id) > 100:
            raise ValueError("call_id 必须是 1～100 字符的非空字符串")
        if not isinstance(tool_id, str) or not tool_id.strip():
            raise ValueError("tool_id 必须是非空字符串")
        deadline = time.monotonic() + timeout_seconds
        if not self._lock.acquire(timeout=timeout_seconds):
            return self._failure(call_id, tool_id, "timeout", "等待执行器超时")
        try:
            return self._execute(call_id, tool_id, arguments, deadline)
        finally:
            self._lock.release()

    def _execute(self, call_id: str, tool_id: str, arguments: Mapping, deadline: float) -> dict:
        if self._count >= self._max_calls:
            return self._failure(call_id, tool_id, "budget_exhausted", "执行次数已达上限")
        self._count += 1  # 拒绝、查询及等待确认均计入，不能绕过 loop 无限调用。
        if deadline <= time.monotonic():
            return self._failure(call_id, tool_id, "timeout", "执行预算已耗尽")
        try:
            tool = self._registry.get(tool_id)
        except KeyError:
            return self._failure(call_id, tool_id, "unknown_tool", "工具不在允许的注册表中")
        try:
            if not isinstance(arguments, Mapping):
                raise InvalidArguments("arguments 必须为对象")
            args = json.loads(json_text(dict(arguments)))
            tool.validate(args)
        except (ValueError, TypeError, OverflowError, RecursionError):
            return self._failure(call_id, tool_id, "invalid_arguments", "工具参数不符合契约")
        fingerprint = hashlib.sha256(
            json.dumps(
                [tool_id, args], ensure_ascii=False, sort_keys=True, allow_nan=False
            ).encode()
        ).hexdigest()
        previous = self._calls.get(call_id)
        if previous is not None and previous.fingerprint != fingerprint:
            return self._failure(
                call_id, tool_id, "call_conflict", "同一调用编号不能改变工具或参数"
            )

        call = None
        attempted_write = False
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return self._failure(call_id, tool_id, "timeout", "执行预算已耗尽")
            # 同一把会话锁覆盖身份检查及实际调用，防止中途切换登录身份。
            with self._transport.request_budget(remaining):
                identity = AuthApi(self._transport).current_user().data
                if (
                    not isinstance(identity, dict)
                    or type(identity.get("is_staff")) is not bool
                    or not isinstance(identity.get("username"), str)
                ):
                    raise BusinessApiProtocolError("身份响应不合法")
                if identity["username"] != self._username:
                    return self._failure(
                        call_id, tool_id, "identity_mismatch", "业务会话身份已变化"
                    )
                if tool.admin and not identity["is_staff"]:
                    return self._failure(call_id, tool_id, "forbidden", "此工具需要管理员权限")
                call = previous or (self._writes.get(fingerprint) if tool.writes else None)
                if call is None:
                    call = _Call(
                        tool_id,
                        args,
                        fingerprint,
                        str(uuid4()) if tool.writes else None,
                        time.monotonic() + self._ttl,
                    )
                    if tool.writes:
                        self._writes[fingerprint] = call
                self._calls[call_id] = call
                if call.result is not None:
                    result = deepcopy(call.result)
                    result["call_id"] = call_id
                    return result
                if tool.writes:
                    if time.monotonic() >= call.expires_at:
                        return self._failure(call_id, tool_id, "confirmation_expired", "确认已过期")
                    if not call.approved:
                        return {
                            "call_id": call_id,
                            "tool_id": tool_id,
                            "status": "confirmation_required",
                            "result": None,
                            "error": None,
                            "confirmation": {
                                "tool_id": tool_id,
                                "arguments": deepcopy(call.arguments),
                                "description": tool.description,
                                "expires_in_seconds": max(0, call.expires_at - time.monotonic()),
                            },
                        }
                if time.monotonic() >= deadline:
                    return self._failure(call_id, tool_id, "timeout", "执行预算已耗尽")
                attempted_write = tool.writes
                response = tool.invoke(self._transport, call.arguments, call.operation_key)
                if time.monotonic() >= deadline:
                    raise BusinessApiConnectionError("响应超过剩余预算")
                data = self._response_data(tool, response, call.arguments)
                value = (
                    {"operation_key": call.operation_key, "response": data} if tool.writes else data
                )
                result = {
                    "call_id": call_id,
                    "tool_id": tool_id,
                    "status": "success",
                    "result": value,
                    "error": None,
                }
        except BusinessApiHttpError as error:
            uncertain = attempted_write and (error.status_code >= 500 or error.status_code == 408)
            result = self._failure(
                call_id,
                tool_id,
                error.code,
                "服务异常，请核实原操作" if uncertain else error.message[:400],
                call if uncertain else None,
            )
        except BusinessApiConnectionError:
            result = self._failure(
                call_id,
                tool_id,
                "connection_error",
                "连接失败或执行超时",
                call if attempted_write else None,
            )
        except BusinessApiProtocolError:
            result = self._failure(
                call_id,
                tool_id,
                "protocol_error",
                "业务响应不符合契约",
                call if attempted_write else None,
            )
        except Exception:
            # 不把内部异常或凭据回传给模型；已尝试写入时不能断言失败。
            result = self._failure(
                call_id,
                tool_id,
                "internal_error",
                "执行器内部错误，需排查程序",
                call if attempted_write else None,
            )
        if call is not None:
            call.result = deepcopy(result)
        return result

    @staticmethod
    def _response_data(tool: Tool, response: ApiResponse[Any], arguments: Mapping) -> dict:
        if not 200 <= response.status_code < 300 or not isinstance(response.data, dict):
            raise BusinessApiProtocolError("HTTP 状态或业务数据格式异常")
        try:
            data = json.loads(json_text(response.data))
        except (ValueError, TypeError):
            raise BusinessApiProtocolError("响应不是合法 JSON 数据") from None
        if not isinstance(data, dict):
            raise BusinessApiProtocolError("响应必须是 JSON 对象")
        if tool.writes:
            entity = data.get("data")
            if (
                not isinstance(entity, dict)
                or type(entity.get("id")) is not int
                or type(data.get("replayed")) is not bool
            ):
                raise BusinessApiProtocolError("写入结果缺少实体或重放标记")
        elif tool.mode == "query":
            if (
                not isinstance(data.get("results"), list)
                or any(type(data.get(k)) is not int for k in ("count", "page", "page_size"))
                or data["count"] < 0
                or data["page"] < 1
                or data["page_size"] < 1
            ):
                raise BusinessApiProtocolError("分页数据格式异常")
        elif tool.tool_id == "get_operation":
            if (
                data.get("committed") is not True
                or not isinstance(data.get("key"), str)
                or "result" not in data
            ):
                raise BusinessApiProtocolError("操作记录格式异常")
        elif type(data.get("id")) is not int:
            raise BusinessApiProtocolError("详情缺少实体 ID")
        entity = data["data"] if tool.writes else data
        if tool.resource and tool.resource.endswith("_id"):
            if entity.get("id") != arguments[tool.resource]:
                raise BusinessApiProtocolError("响应实体与请求目标不匹配")
        if tool.tool_id == "get_operation" and data["key"] != arguments["idempotency_key"]:
            raise BusinessApiProtocolError("返回的操作编号不匹配")
        return data

    @staticmethod
    def _failure(
        call_id: str, tool_id: str, code: str, message: str, uncertain_call: _Call | None = None,
    ) -> dict:
        return {
            "call_id": call_id,
            "tool_id": tool_id,
            "status": "unknown" if uncertain_call else "error",
            "result": {"operation_key": uncertain_call.operation_key, "response": None}
            if uncertain_call
            else None,
            "error": {"code": code, "message": message},
        }

    @staticmethod
    def _positive_timeout(value: object) -> None:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
        ):
            raise ValueError("超时必须为有限正数")
