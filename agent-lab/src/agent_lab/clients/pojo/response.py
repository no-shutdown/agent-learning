"""通用响应对象及 JSON 响应类型。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeAlias, TypedDict, TypeVar


DataT = TypeVar("DataT")
JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


@dataclass(frozen=True, slots=True)
class ApiResponse(Generic[DataT]):
    """HTTP 响应的通用传输包装，data 是对应接口的响应数据类型。"""

    status_code: int
    headers: dict[str, str]
    data: DataT


class ApiErrorData(TypedDict):
    """业务 API 的错误详情。"""

    code: str
    message: str


class ApiErrorEnvelope(TypedDict):
    """业务 API 的统一错误响应体。"""

    error: ApiErrorData


class PageResponse(TypedDict, Generic[DataT]):
    """业务 API 列表接口的通用分页响应体。"""

    count: int
    page: int
    page_size: int
    results: list[DataT]


class WriteResponse(TypedDict, Generic[DataT]):
    """业务 API 写入接口的通用结果及幂等重放标记。"""

    data: DataT
    replayed: bool
