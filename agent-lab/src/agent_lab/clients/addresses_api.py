"""当前用户地址簿查询和维护 API。"""

from typing import TypedDict, cast

from .pojo import ApiRequest, ApiResponse, PageResponse, PaginationQuery, WriteResponse
from .transport import BusinessApiTransport


class AddressFields(TypedDict):
    recipient: str
    phone: str
    province: str
    city: str
    district: str
    detail: str


class CreateAddressRequest(AddressFields):
    pass


class UpdateAddressRequest(AddressFields):
    version: int


class AddressResponse(TypedDict):
    id: int
    version: int
    recipient: str
    phone: str
    province: str
    city: str
    district: str
    detail: str


class AddressesApi:
    """提供当前登录用户自己的地址簿接口。"""

    def __init__(self, transport: BusinessApiTransport) -> None:
        self._transport = transport

    def list_addresses(
        self, query: PaginationQuery | None = None
    ) -> ApiResponse[PageResponse[AddressResponse]]:
        """分页查询当前用户的收货地址。"""
        return cast(
            ApiResponse[PageResponse[AddressResponse]],
            self._transport.send(ApiRequest("GET", "addresses", query=query)),
        )

    def create_address(
        self, body: CreateAddressRequest, *, idempotency_key: str
    ) -> ApiResponse[WriteResponse[AddressResponse]]:
        """新增当前用户的收货地址；每个逻辑写入必须提供唯一幂等键。"""
        return cast(
            ApiResponse[WriteResponse[AddressResponse]],
            self._transport.send(
                ApiRequest(
                    "POST",
                    "addresses",
                    body=body,
                    requires_csrf=True,
                    idempotency_key=idempotency_key,
                )
            ),
        )

    def update_address(
        self,
        address_id: int,
        body: UpdateAddressRequest,
        *,
        idempotency_key: str,
    ) -> ApiResponse[WriteResponse[AddressResponse]]:
        """按地址版本更新当前用户的收货地址；每个逻辑写入必须提供唯一幂等键。
        """
        return cast(
            ApiResponse[WriteResponse[AddressResponse]],
            self._transport.send(
                ApiRequest(
                    "PUT",
                    f"addresses/{self._path_id(address_id)}",
                    body=body,
                    requires_csrf=True,
                    idempotency_key=idempotency_key,
                )
            ),
        )

    @staticmethod
    def _path_id(value: int) -> str:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError("resource ID must be a positive integer")
        return str(value)
