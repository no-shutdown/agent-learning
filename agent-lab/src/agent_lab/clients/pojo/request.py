"""通用请求对象及查询参数类型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, Literal, Mapping, NotRequired, TypeAlias, TypedDict, TypeVar


HttpMethod: TypeAlias = Literal["GET", "POST", "PUT"]
QueryValue: TypeAlias = str | int
BodyT = TypeVar("BodyT")


@dataclass(frozen=True, slots=True)
class ApiRequest(Generic[BodyT]):
    """HTTP 请求的通用传输包装，不改变业务接口实际发送的 JSON 结构。"""

    method: HttpMethod
    path: str
    query: Mapping[str, QueryValue] | None = None
    body: BodyT | None = None
    headers: Mapping[str, str] = field(default_factory=dict)
    requires_csrf: bool = False
    idempotency_key: str | None = None


class PaginationQuery(TypedDict):
    """列表接口通用分页参数。"""

    page: NotRequired[int]
    page_size: NotRequired[int]
