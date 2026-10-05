"""LLM 主导的对话与工具调用循环。

本模块只负责组织模型消息、识别模型的最终回答或工具请求，并把工具请求交给
注入的 runtime executor。它不直接调用业务工具，也不负责身份认证或授权。
"""

from __future__ import annotations

from copy import deepcopy
import math
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal

from ..prompts.loader import load_prompt
from ..models.contracts import ChatModel, Message, ModelRequest, ModelResponse
from .tracing import emit
from ..tools.registry import ToolRegistry
from .contracts import ExecutionProtocolError, RuntimeExecutor, ToolCall, validate_execution_result


DEFAULT_MAX_MODEL_CALLS = 8
DEFAULT_MAX_TOOL_CALLS = 16
DEFAULT_TIMEOUT_SECONDS = 120.0

LoopStatus = Literal["completed", "confirmation_required", "budget_exhausted"]


class LoopError(RuntimeError):
    """Agent 循环执行错误的基类。"""


class LoopProtocolError(LoopError):
    """模型或 runtime executor 返回了不符合协议的数据。"""


@dataclass(frozen=True, slots=True)
class LoopResult:
    """一次任务循环的结果和可供上层运行时接续的消息。"""

    status: LoopStatus
    reply: str | None
    messages: tuple[Message, ...]
    model_calls: int
    tool_calls: int
    prompt_version: str
    pending_calls: tuple[ToolCall, ...] = ()
    pending_confirmation: Mapping[str, Any] | None = None


def run_loop(
    user_message: str | None,
    *,
    model: ChatModel,
    executor: RuntimeExecutor,
    registry: ToolRegistry,
    history: Sequence[Message] = (),
    max_model_calls: int = DEFAULT_MAX_MODEL_CALLS,
    max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> LoopResult:
    """运行一个任务，直到模型回答、执行器要求确认或预算耗尽。

    参数：
      - ``user_message``：本次用户请求。
      - ``model``：实现统一 ``generate(ModelRequest) -> ModelResponse`` 的模型客户端。
      - ``executor``：runtime executor；所有模型工具请求都必须经它处理。
      - ``registry``：向模型展示的工具集合。它不是权限凭证，executor 仍须逐次授权。
      - ``max_model_calls`` / ``max_tool_calls``：本次任务的硬调用上限。
      - ``timeout_seconds``：任务总时限；executor 每次收到剩余时间并须为调用设超时。

    只有模型的原生 ``tool_calls`` 可触发工具执行；正文始终视为回答文本。
    每个结果会以带有相同 call_id 的工具消息回填，之后再请求模型决定下一步。
    所有工具调用交给执行器；调用去重、权限和确认不在循环中实现。
    """
    if user_message is not None and (not isinstance(user_message, str) or not user_message.strip()):
        raise ValueError("user_message 必须是非空字符串")
    _validate_limit(max_model_calls, "max_model_calls")
    _validate_limit(max_tool_calls, "max_tool_calls")
    _validate_timeout(timeout_seconds)

    definitions = registry.definitions()
    prompt = load_prompt()
    emit(
        "loop.started",
        prompt_version=prompt.version,
        history_messages=len(history),
        max_model_calls=max_model_calls,
        max_tool_calls=max_tool_calls,
        timeout_seconds=timeout_seconds,
    )

    # history 仅由服务端保存的对话状态提供，不从客户端请求接收 role/messages。
    messages = deepcopy(list(history)) if history else [Message("system", prompt.text)]
    if user_message is not None:
        messages.append(Message("user", user_message.strip()))
    started_at = time.monotonic()
    model_calls = 0
    tool_calls = 0

    while True:
        if model_calls >= max_model_calls or _remaining_time(started_at, timeout_seconds) <= 0:
            return _result(
                "budget_exhausted", None, messages, model_calls, tool_calls, prompt.version
            )

        remaining = _remaining_time(started_at, timeout_seconds)
        if remaining <= 0:
            return _result(
                "budget_exhausted", None, messages, model_calls, tool_calls, prompt.version
            )
        response = model.generate(
            ModelRequest(messages=deepcopy(messages), tools=definitions),
            timeout_seconds=remaining,
        )
        model_calls += 1
        if not isinstance(response, ModelResponse):
            raise LoopProtocolError("模型适配器必须返回 ModelResponse")
        content = response.text
        requested_calls = response.tool_calls
        messages.append(Message("assistant", content, requested_calls))
        if not requested_calls:
            if not content.strip():
                raise LoopProtocolError("模型既未返回工具调用，也未返回非空回答")
            if _remaining_time(started_at, timeout_seconds) <= 0:
                return _result(
                    "budget_exhausted", None, messages, model_calls, tool_calls, prompt.version
                )
            return _result("completed", content, messages, model_calls, tool_calls, prompt.version)

        if _remaining_time(started_at, timeout_seconds) <= 0:
            return _result(
                "budget_exhausted",
                None,
                messages,
                model_calls,
                tool_calls,
                prompt.version,
                pending_calls=requested_calls,
            )

        remaining_tool_budget = max_tool_calls - tool_calls
        if len(requested_calls) > remaining_tool_budget:
            return _result(
                "budget_exhausted",
                None,
                messages,
                model_calls,
                tool_calls,
                prompt.version,
                pending_calls=requested_calls,
            )

        for index, call in enumerate(requested_calls):
            remaining = _remaining_time(started_at, timeout_seconds)
            if remaining <= 0:
                return _result(
                    "budget_exhausted",
                    None,
                    messages,
                    model_calls,
                    tool_calls,
                    prompt.version,
                    pending_calls=requested_calls[index:],
                )

            # 在调用 executor 前计数，确认等待也消耗本次任务预算。
            tool_calls += 1
            execution = executor.execute(
                call_id=call.call_id,
                tool_id=call.tool_id,
                arguments=call.arguments,
                timeout_seconds=remaining,
            )
            try:
                status, result_data, confirmation = validate_execution_result(execution, call)
            except ExecutionProtocolError as error:
                raise LoopProtocolError(str(error)) from error

            if status == "confirmation_required":
                return _result(
                    "confirmation_required",
                    None,
                    messages,
                    model_calls,
                    tool_calls,
                    prompt.version,
                    pending_calls=requested_calls[index:],
                    pending_confirmation=confirmation,
                )

            messages.append(Message("tool", tool_result=result_data))


def resume_loop(
    previous: LoopResult,
    *,
    model: ChatModel,
    executor: RuntimeExecutor,
    registry: ToolRegistry,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_model_calls: int = DEFAULT_MAX_MODEL_CALLS,
    max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS,
) -> LoopResult:
    """可信应用完成确认后，先执行保存的原请求，再继续模型循环。

    不从客户端接收新参数替换 pending_calls；暂停期间不消耗执行时限。
    本次恢复仍使用剩余调用次数。多个写请求逐个取得确认。
    """
    _validate_timeout(timeout_seconds)
    if previous.status != "confirmation_required" or not previous.pending_calls:
        raise ValueError("没有待恢复的确认请求")
    emit(
        "loop.resumed",
        prompt_version=previous.prompt_version,
        pending_calls=[
            {"call_id": c.call_id, "tool_id": c.tool_id} for c in previous.pending_calls
        ],
    )
    started = time.monotonic()
    messages = deepcopy(list(previous.messages))
    used = previous.tool_calls
    for index, call in enumerate(previous.pending_calls):
        remaining = _remaining_time(started, timeout_seconds)
        if used >= max_tool_calls or remaining <= 0:
            return replace(
                previous,
                status="budget_exhausted",
                messages=tuple(messages),
                tool_calls=used,
                pending_calls=previous.pending_calls[index:],
            )
        used += 1
        execution = executor.execute(
            call_id=call.call_id,
            tool_id=call.tool_id,
            arguments=call.arguments,
            timeout_seconds=remaining,
        )
        try:
            status, data, confirmation = validate_execution_result(execution, call)
        except ExecutionProtocolError as error:
            raise LoopProtocolError(str(error)) from error
        if status == "confirmation_required":
            return replace(
                previous,
                messages=tuple(messages),
                tool_calls=used,
                pending_calls=previous.pending_calls[index:],
                pending_confirmation=confirmation,
            )
        messages.append(Message("tool", tool_result=data))
    remaining = _remaining_time(started, timeout_seconds)
    if used >= max_tool_calls or previous.model_calls >= max_model_calls or remaining <= 0:
        return replace(
            previous,
            status="budget_exhausted",
            messages=tuple(messages),
            tool_calls=used,
            pending_calls=(),
            pending_confirmation=None,
        )
    result = run_loop(
        None,
        model=model,
        executor=executor,
        registry=registry,
        history=messages,
        timeout_seconds=remaining,
        max_model_calls=max_model_calls - previous.model_calls,
        max_tool_calls=max_tool_calls - used,
    )
    return replace(
        result,
        model_calls=result.model_calls + previous.model_calls,
        tool_calls=result.tool_calls + used,
        prompt_version=previous.prompt_version,
    )


def _remaining_time(started_at: float, timeout_seconds: float) -> float:
    return timeout_seconds - (time.monotonic() - started_at)


def _validate_limit(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} 必须是大于零的整数")


def _validate_timeout(value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("timeout_seconds 必须是大于零的有限数值")
    try:
        timeout = float(value)
    except (OverflowError, ValueError) as error:
        raise ValueError("timeout_seconds 必须是大于零的有限数值") from error
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout_seconds 必须是大于零的有限数值")


def _result(
    status: LoopStatus,
    reply: str | None,
    messages: Sequence[Message],
    model_calls: int,
    tool_calls: int,
    prompt_version: str,
    *,
    pending_calls: Sequence[ToolCall] = (),
    pending_confirmation: Mapping[str, Any] | None = None,
) -> LoopResult:
    return LoopResult(
        status=status,
        reply=reply,
        messages=tuple(messages),
        model_calls=model_calls,
        tool_calls=tool_calls,
        prompt_version=prompt_version,
        pending_calls=tuple(pending_calls),
        pending_confirmation=pending_confirmation,
    )


__all__ = [
    "DEFAULT_MAX_MODEL_CALLS",
    "DEFAULT_MAX_TOOL_CALLS",
    "DEFAULT_TIMEOUT_SECONDS",
    "LoopError",
    "LoopProtocolError",
    "LoopResult",
    "RuntimeExecutor",
    "ToolCall",
    "run_loop",
    "resume_loop",
]
