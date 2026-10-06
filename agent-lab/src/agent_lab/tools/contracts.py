"""工具契约及其使用的 JSON Schema 子集；不负责模型决策。"""

from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal
import re
from typing import Callable

from ..clients import (
    AddressesApi,
    BusinessApiTransport,
    OperationsApi,
    OrdersApi,
    ProductsApi,
    validate_idempotency_key,
)


def integer(description: str, minimum: int = 1, maximum: int = 1_000_000_000) -> dict:
    return dict(type="integer", description=description, minimum=minimum, maximum=maximum)


def string(description: str, maximum: int, *, required: bool = True, **extra) -> dict:
    return dict(
        type="string", description=description, minLength=int(required), maxLength=maximum, **extra
    )


def obj(properties: dict, required: tuple | None = None) -> dict:
    return dict(
        type="object",
        properties=properties,
        required=list(properties if required is None else required),
        additionalProperties=False,
    )


ID = integer("从业务查询结果获取的资源 ID，不是显示编号")
VERSION = integer("最近一次查询返回的 version；不要猜测")
PAGE = {
    "page": integer("页码，默认 1"),
    "page_size": integer("每页条数，默认 20，最多 100", maximum=100),
}
SEARCH = {**PAGE, "q": string("搜索关键词", 200, required=False)}


class InvalidArguments(ValueError):
    """模型参数不符合工具契约。"""


def validate(value: object, schema: dict, path: str = "arguments") -> None:
    """仅实现本项目契约用到的约束，不宣称是通用 JSON Schema 引擎。"""
    kind = schema["type"]
    if kind == "object":
        if type(value) is not dict:
            raise InvalidArguments(f"{path} 必须是 {kind}")
        props = schema["properties"]
        if set(value) - set(props) or set(schema["required"]) - set(value):
            raise InvalidArguments(f"{path} 字段缺失或包含未声明字段")
        for key, item in value.items():
            validate(item, props[key], f"{path}.{key}")
    elif kind == "array":
        if type(value) is not list:
            raise InvalidArguments(f"{path} 必须是 {kind}")
        if not schema["minItems"] <= len(value) <= schema["maxItems"]:
            raise InvalidArguments(f"{path} 项目数量超出范围")
        for index, item in enumerate(value):
            validate(item, schema["items"], f"{path}[{index}]")
    elif kind == "integer":
        if type(value) is not int:
            raise InvalidArguments(f"{path} 必须是 {kind}")
        if not schema["minimum"] <= value <= schema["maximum"]:
            raise InvalidArguments(f"{path} 数值超出范围")
    elif kind == "string":
        if type(value) is not str:
            raise InvalidArguments(f"{path} 必须是 {kind}")
        if not schema["minLength"] <= len(value) <= schema["maxLength"]:
            raise InvalidArguments(f"{path} 长度超出范围")
        if schema["minLength"] and not value.strip():
            raise InvalidArguments(f"{path} 不能为空白")
        if "pattern" in schema and re.fullmatch(schema["pattern"], value) is None:
            raise InvalidArguments(f"{path} 格式错误")
    elif kind == "boolean":
        if type(value) is not bool:
            raise InvalidArguments(f"{path} 必须是 {kind}")
    else:
        raise ValueError(f"不支持的工具参数类型：{kind}")
    if "enum" in schema and value not in schema["enum"]:
        raise InvalidArguments(f"{path} 不是允许的枚举值")


def unique_items(arguments: dict) -> None:
    ids = [item["product_id"] for item in arguments["items"]]
    if len(ids) != len(set(ids)):
        raise InvalidArguments("同一商品请合并为一个项目")


def positive_price(arguments: dict) -> None:
    if Decimal(arguments["price"]) < Decimal("0.01"):
        raise InvalidArguments("price 必须至少为 0.01")


@dataclass(frozen=True)
class Tool:
    tool_id: str
    description: str
    parameters: dict
    api: type[AddressesApi | OperationsApi | OrdersApi | ProductsApi]
    method: Callable
    mode: str = "query"  # query / detail / write
    resource: str | None = None
    admin: bool = False
    extra_validation: Callable | None = None

    @property
    def writes(self) -> bool:
        return self.mode == "write"

    def definition(self) -> dict:
        return {
            "tool_id": self.tool_id,
            "description": self.description,
            "parameters": deepcopy(self.parameters),
            "requires_confirmation": self.writes,
            "requires_admin": self.admin,
            "returns": (
                "底层返回 ApiResponse，data 为 {data: 业务对象, replayed: 布尔值}；"
                "异常向调用方抛出，工具不生成运行时状态。"
                if self.writes
                else "底层返回 ApiResponse；data 中列表为 count/page/page_size/results，详情为对象。"
            ),
        }

    def validate(self, arguments: dict) -> None:
        validate(arguments, self.parameters)
        if self.extra_validation:
            self.extra_validation(arguments)

    def invoke(self, transport: BusinessApiTransport, arguments: dict, key: str | None):
        """底层适配调用，保留 ApiResponse 和客户端异常，不是模型执行入口。

        调用前的身份、权限及确认由 runtime/executor.py 负责。这里只检查参数与
        写请求必需的幂等键，不生成键、不重试、不封装对话消息。
        """
        self.validate(arguments)
        if self.writes:
            if not isinstance(key, str):
                raise ValueError("写工具需要由调用方提供幂等键")
            validate_idempotency_key(key)
        # method 是源码注册的函数引用，不按模型提供的名称反射客户端。
        client = self.api(transport)
        body = dict(arguments)
        positional = [body.pop(self.resource)] if self.resource else []
        if self.writes:
            return self.method(client, *positional, body, idempotency_key=key)
        if self.mode == "detail":
            return self.method(client, *positional)
        return self.method(client, body)
