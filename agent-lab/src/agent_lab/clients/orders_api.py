"""客户订单查询、创建和状态操作 API。"""

from typing import Literal, NotRequired, TypedDict, cast
from .pojo import ApiRequest, ApiResponse, PageResponse, PaginationQuery, WriteResponse
from .transport import BusinessApiTransport
from .pojo.request import normalize_query


OrderStatus = Literal["pending_payment", "paid", "shipped", "cancelled"]


class OrderListQuery(PaginationQuery):
    status: NotRequired[OrderStatus]
    q: NotRequired[str]


class OrderItemRequest(TypedDict):
    product_id: int
    quantity: int


class CreateOrderRequest(TypedDict):
    address_id: int
    items: list[OrderItemRequest]
    note: NotRequired[str]


class OrderVersionRequest(TypedDict):
    version: int


class ChangeOrderAddressRequest(OrderVersionRequest):
    address_id: int


class ShipOrderRequest(OrderVersionRequest):
    tracking_no: str


class AddressSnapshot(TypedDict):
    recipient: str
    phone: str
    province: str
    city: str
    district: str
    detail: str


class OrderItemResponse(TypedDict):
    product_id: int
    name: str
    unit_price: str
    quantity: int


class OrderResponse(TypedDict):
    id: int
    number: str
    status: OrderStatus
    status_label: str
    total: str
    address: AddressSnapshot
    note: str
    tracking_no: str | None
    version: int
    created_at: str
    items: list[OrderItemResponse]


class OrdersApi:
    """提供当前用户订单及管理员订单查询、订单创建和订单操作接口。"""

    def __init__(self, transport: BusinessApiTransport) -> None:
        self._transport = transport

    def list_orders(
        self, query: OrderListQuery | None = None
    ) -> ApiResponse[PageResponse[OrderResponse]]:
        """分页查询当前用户订单，可按状态或编号、商品名、备注筛选。"""
        return cast(
            ApiResponse[PageResponse[OrderResponse]],
            self._transport.send(ApiRequest("GET", "orders", query=normalize_query(query))),
        )

    def list_admin_orders(
        self, query: OrderListQuery | None = None
    ) -> ApiResponse[PageResponse[OrderResponse]]:
        """管理员分页查询全部订单，可按状态、编号、商品名或备注筛选。"""
        return cast(
            ApiResponse[PageResponse[OrderResponse]],
            self._transport.send(ApiRequest("GET", "manage/orders", query=normalize_query(query))),
        )

    def get_order(self, order_id: int) -> ApiResponse[OrderResponse]:
        """查询当前用户某个订单的详情、地址快照、商品明细和版本。"""
        return cast(
            ApiResponse[OrderResponse],
            self._transport.send(
                ApiRequest("GET", f"orders/{self._path_id(order_id)}")
            ),
        )

    def create_order(
        self, body: CreateOrderRequest, *, idempotency_key: str
    ) -> ApiResponse[WriteResponse[OrderResponse]]:
        """创建订单并扣减库存；每个逻辑写入必须提供唯一幂等键。"""
        return self._order_write("orders", body, idempotency_key)

    def pay_order(
        self,
        order_id: int,
        body: OrderVersionRequest,
        *,
        idempotency_key: str,
    ) -> ApiResponse[WriteResponse[OrderResponse]]:
        """模拟支付待支付订单，并通过版本号避免覆盖并发更新。"""
        return self._order_action(order_id, "pay", body, idempotency_key)

    def cancel_order(
        self,
        order_id: int,
        body: OrderVersionRequest,
        *,
        idempotency_key: str,
    ) -> ApiResponse[WriteResponse[OrderResponse]]:
        """取消允许取消的订单，并由业务服务按规则恢复库存。"""
        return self._order_action(order_id, "cancel", body, idempotency_key)

    def change_order_address(
        self,
        order_id: int,
        body: ChangeOrderAddressRequest,
        *,
        idempotency_key: str,
    ) -> ApiResponse[WriteResponse[OrderResponse]]:
        """修改尚未发货订单的收货地址，并校验订单版本。"""
        return self._order_action(order_id, "address", body, idempotency_key)

    def ship_order(
        self,
        order_id: int,
        body: ShipOrderRequest,
        *,
        idempotency_key: str,
    ) -> ApiResponse[WriteResponse[OrderResponse]]:
        """管理员为待发货订单登记物流单号并发货。"""
        return self._order_action(order_id, "ship", body, idempotency_key)

    def _order_action(
        self,
        order_id: int,
        action: Literal["pay", "cancel", "address", "ship"],
        body: OrderVersionRequest | ChangeOrderAddressRequest | ShipOrderRequest,
        idempotency_key: str,
    ) -> ApiResponse[WriteResponse[OrderResponse]]:
        return self._order_write(
            f"orders/{self._path_id(order_id)}/{action}", body, idempotency_key
        )

    def _order_write(
        self,
        path: str,
        body: CreateOrderRequest
        | OrderVersionRequest
        | ChangeOrderAddressRequest
        | ShipOrderRequest,
        idempotency_key: str,
    ) -> ApiResponse[WriteResponse[OrderResponse]]:
        return cast(
            ApiResponse[WriteResponse[OrderResponse]],
            self._transport.send(
                ApiRequest(
                    "POST",
                    path,
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
