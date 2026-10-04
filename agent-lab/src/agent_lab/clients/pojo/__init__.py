"""业务 API 通用请求与响应对象。"""

from .request import ApiRequest, HttpMethod, PaginationQuery, QueryValue
from .response import (
    ApiErrorData,
    ApiErrorEnvelope,
    ApiResponse,
    DataT,
    JsonScalar,
    JsonValue,
    PageResponse,
    WriteResponse,
)

__all__ = [
    "ApiErrorData",
    "ApiErrorEnvelope",
    "ApiRequest",
    "ApiResponse",
    "DataT",
    "HttpMethod",
    "JsonScalar",
    "JsonValue",
    "PageResponse",
    "PaginationQuery",
    "QueryValue",
    "WriteResponse",
]
