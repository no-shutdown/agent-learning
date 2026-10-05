"""运行时工具请求和结果协议；不负责模型决策或执行业务。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Literal, Protocol
from ..models.contracts import ToolCall

ExecutionStatus = Literal["success", "error", "unknown", "confirmation_required"]


class ExecutionProtocolError(ValueError):
    """执行器的结果无法安全地回填给模型。"""


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


class RuntimeExecutor(Protocol):
    """循环唯一允许的工具执行入口。

    ``execute`` 必须在任何副作用发生前校验工具、可信身份、权限、参数、确认状态
    和剩余超时。它返回的映射必须包含 call_id、tool_id、status、result、error；
    等待确认时还须提供 confirmation。这里不提供直接调用 Tool.invoke 的后门。
    """

    def execute(
        self,
        *,
        call_id: str,
        tool_id: str,
        arguments: Mapping[str, Any],
        timeout_seconds: float,
    ) -> Mapping[str, Any]: ...


def validate_execution_result(
    value: Mapping[str, Any], call: ToolCall
) -> tuple[ExecutionStatus, dict[str, Any], Mapping[str, Any] | None]:
    if not isinstance(value, Mapping):
        raise ExecutionProtocolError("runtime executor 必须返回对象")
    if value.get("call_id") != call.call_id or value.get("tool_id") != call.tool_id:
        raise ExecutionProtocolError("runtime executor 结果与工具请求的 call_id/tool_id 不匹配")
    status = value.get("status")
    if not isinstance(status, str) or status not in {
        "success",
        "error",
        "unknown",
        "confirmation_required",
    }:
        raise ExecutionProtocolError("runtime executor 返回了不支持的 status")

    if status == "confirmation_required":
        confirmation = value.get("confirmation")
        if not isinstance(confirmation, Mapping):
            raise ExecutionProtocolError("等待确认时 executor 必须返回 confirmation 对象")
        try:
            safe_confirmation = json.loads(json_text(dict(confirmation)))
        except (TypeError, ValueError) as error:
            raise ExecutionProtocolError("confirmation 必须是 JSON 对象") from error
        return status, {}, safe_confirmation

    result = value.get("result")
    error = value.get("error")
    if error is not None:
        if not isinstance(error, Mapping):
            raise ExecutionProtocolError("executor error 必须是对象或 null")
        if not isinstance(error.get("code"), str) or not isinstance(error.get("message"), str):
            raise ExecutionProtocolError("executor error 必须包含字符串 code 和 message")
        error = {"code": error["code"], "message": error["message"]}
    if status == "error" and error is None:
        raise ExecutionProtocolError("executor status=error 时必须提供 error")
    if status == "success" and error is not None:
        raise ExecutionProtocolError("executor status=success 时 error 必须为 null")
    try:
        safe_result = json.loads(json_text(result))
    except (TypeError, ValueError) as error:
        raise ExecutionProtocolError("executor result 必须是 JSON 数据") from error
    return (
        status,
        {
            "call_id": call.call_id,
            "tool_id": call.tool_id,
            "status": status,
            "result": safe_result,
            "error": error,
        },
        None,
    )
