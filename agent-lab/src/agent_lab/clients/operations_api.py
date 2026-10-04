"""当前用户的业务操作记录查询 API。"""

from typing import Literal, TypedDict, cast
from urllib.parse import quote

from .pojo import ApiRequest, ApiResponse, JsonValue, PageResponse, PaginationQuery
from .transport import BusinessApiTransport, validate_idempotency_key


class OperationSummaryResponse(TypedDict):
    key: str
    action: str
    target: str
    created_at: str


class OperationDetailResponse(TypedDict):
    key: str
    action: str
    result: JsonValue
    committed: Literal[True]


class OperationsApi:
    """提供当前登录用户已成功提交的操作记录查询接口。"""

    def __init__(self, transport: BusinessApiTransport) -> None:
        self._transport = transport

    def list_operations(
        self, query: PaginationQuery | None = None
    ) -> ApiResponse[PageResponse[OperationSummaryResponse]]:
        """分页查询当前用户已提交操作的摘要列表。"""
        return cast(
            ApiResponse[PageResponse[OperationSummaryResponse]],
            self._transport.send(ApiRequest("GET", "operations", query=query)),
        )

    def get_operation(self, idempotency_key: str) -> ApiResponse[OperationDetailResponse]:
        """按幂等键查询原始操作结果，用于核实写入是否已提交。"""
        validate_idempotency_key(idempotency_key)
        return cast(
            ApiResponse[OperationDetailResponse],
            self._transport.send(
                ApiRequest(
                    "GET",
                    f"operations/{quote(idempotency_key, safe='')}",
                )
            ),
        )
