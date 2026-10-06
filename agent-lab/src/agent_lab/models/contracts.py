"""项目统一的模型协议；不包含具体服务的 HTTP 字段或响应封装。"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import json
from typing import Any, Literal, Protocol


class ModelError(RuntimeError):
    """模型适配器的统一错误基类。"""


class ModelProtocolError(ModelError):
    """模型输入或输出不符合统一协议。"""


def json_copy(value: object) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as error:
        raise ModelProtocolError("模型协议数据必须可序列化为 JSON") from error


@dataclass(frozen=True, slots=True)
class ToolCall:
    call_id: str
    tool_id: str
    arguments: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.call_id, str) or not 1 <= len(self.call_id.strip()) <= 100:
            raise ModelProtocolError("工具调用编号无效")
        if not isinstance(self.tool_id, str) or not self.tool_id.strip():
            raise ModelProtocolError("工具名称无效")
        if not isinstance(self.arguments, Mapping):
            raise ModelProtocolError("工具参数必须是对象")
        object.__setattr__(self, "arguments", json_copy(dict(self.arguments)))


@dataclass(frozen=True, slots=True)
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_result: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.role not in {"system", "user", "assistant", "tool"} or not isinstance(
            self.text, str
        ):
            raise ModelProtocolError("消息角色或文本无效")
        if not isinstance(self.tool_calls, tuple) or any(
            not isinstance(c, ToolCall) for c in self.tool_calls
        ):
            raise ModelProtocolError("工具请求必须是 ToolCall 元组")
        if self.tool_calls and self.role != "assistant":
            raise ModelProtocolError("只有助手消息可以包含工具请求")
        if self.role == "tool":
            if not isinstance(self.tool_result, Mapping):
                raise ModelProtocolError("工具消息缺少结果")
            if not all(
                isinstance(self.tool_result.get(k), str) and self.tool_result[k]
                for k in ("call_id", "tool_id")
            ):
                raise ModelProtocolError("工具结果缺少关联编号")
        elif self.tool_result is not None:
            raise ModelProtocolError("只有工具消息可以包含工具结果")
        if self.tool_result is not None:
            object.__setattr__(self, "tool_result", json_copy(dict(self.tool_result)))


@dataclass(frozen=True, slots=True)
class ModelRequest:
    messages: Sequence[Message]
    tools: Sequence[Mapping[str, Any]] = ()

    def __post_init__(self) -> None:
        if not self.messages or any(not isinstance(m, Message) for m in self.messages):
            raise ModelProtocolError("messages 必须包含统一 Message")
        object.__setattr__(self, "messages", tuple(self.messages))
        object.__setattr__(self, "tools", tuple(json_copy(list(self.tools))))


@dataclass(frozen=True, slots=True)
class ModelResponse:
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise ModelProtocolError("模型回答必须为字符串")
        if not isinstance(self.tool_calls, tuple) or any(
            not isinstance(c, ToolCall) for c in self.tool_calls
        ):
            raise ModelProtocolError("工具请求必须是 ToolCall 元组")
        object.__setattr__(self, "metadata", json_copy(dict(self.metadata)))


class ChatModel(Protocol):
    def generate(
        self, request: ModelRequest, *, timeout_seconds: float | None = None
    ) -> ModelResponse: ...
