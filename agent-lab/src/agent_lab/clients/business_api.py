"""business-demo API 聚合入口；端点实现按业务模块拆分在对应 *_api.py 中。"""

from .addresses_api import (
    AddressFields,
    AddressResponse,
    AddressesApi,
    CreateAddressRequest,
    UpdateAddressRequest,
)
from .assistant_api import AssistantApi, ChatRequest, ChatResponse
from .auth_api import (
    AuthApi,
    CurrentUserResponse,
    CsrfResponse,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
)
from .operations_api import (
    OperationDetailResponse,
    OperationSummaryResponse,
    OperationsApi,
)
from .orders_api import (
    AddressSnapshot,
    ChangeOrderAddressRequest,
    CreateOrderRequest,
    OrderItemRequest,
    OrderItemResponse,
    OrderListQuery,
    OrderResponse,
    OrderStatus,
    OrderVersionRequest,
    OrdersApi,
    ShipOrderRequest,
)
from .pojo import (
    ApiErrorData,
    ApiErrorEnvelope,
    ApiRequest,
    ApiResponse,
    PageResponse,
    PaginationQuery,
    WriteResponse,
)
from .products_api import (
    CreateProductRequest,
    ProductFields,
    ProductListQuery,
    ProductResponse,
    ProductsApi,
    UpdateProductRequest,
)
from .system_api import HealthResponse, SystemApi
from .transport import (
    API_BASE_URL_ENV,
    DEFAULT_API_BASE_URL,
    DEFAULT_TIMEOUT_SECONDS,
    BusinessApiConnectionError,
    BusinessApiException,
    BusinessApiHttpError,
    BusinessApiProtocolError,
    BusinessApiTransport,
    validate_idempotency_key,
)


class BusinessApiClient:
    """业务 API 聚合客户端，同时提供按模块分组和旧版平铺调用方式。

    每个实例拥有独立的登录 Cookie 和 CSRF token。不同业务身份必须分别
    创建客户端实例，不能共享管理员或其他用户的会话。
    """

    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._transport = BusinessApiTransport(
            base_url,
            timeout_seconds=timeout_seconds,
        )
        self.system = SystemApi(self._transport)
        self.auth = AuthApi(self._transport)
        self.products = ProductsApi(self._transport)
        self.addresses = AddressesApi(self._transport)
        self.orders = OrdersApi(self._transport)
        self.operations = OperationsApi(self._transport)
        self.assistant = AssistantApi(self._transport)

    def clear_session(self) -> None:
        """清除当前客户端保存的 Cookie 和 CSRF token，通常用于切换账号。"""
        self._transport.clear_session()

    def health(self) -> ApiResponse[HealthResponse]:
        """查询 business-demo 服务健康状态。"""
        return self.system.health()

    def get_csrf(self) -> ApiResponse[CsrfResponse]:
        """获取 CSRF token，供登录或受保护的写请求使用。"""
        return self.auth.get_csrf()

    def login(self, username: str, password: str) -> ApiResponse[LoginResponse]:
        """使用用户名和密码登录 business-demo。"""
        return self.auth.login(username, password)

    def logout(self) -> ApiResponse[LogoutResponse]:
        """退出当前 business-demo 登录会话。"""
        return self.auth.logout()

    def current_user(self) -> ApiResponse[CurrentUserResponse]:
        """查询当前登录用户和管理员身份标记。"""
        return self.auth.current_user()

    def list_products(
        self, query: ProductListQuery | None = None
    ) -> ApiResponse[PageResponse[ProductResponse]]:
        """分页查询上架商品，可按名称搜索。"""
        return self.products.list_products(query)

    def get_product(self, product_id: int) -> ApiResponse[ProductResponse]:
        """查询指定上架商品详情。"""
        return self.products.get_product(product_id)

    def list_admin_products(
        self, query: ProductListQuery | None = None
    ) -> ApiResponse[PageResponse[ProductResponse]]:
        """管理员分页查询全部商品，包括已下架商品。"""
        return self.products.list_admin_products(query)

    def create_product(
        self, body: CreateProductRequest, *, idempotency_key: str
    ) -> ApiResponse[WriteResponse[ProductResponse]]:
        """管理员创建商品，并用幂等键保护重复提交。"""
        return self.products.create_product(body, idempotency_key=idempotency_key)

    def update_product(
        self,
        product_id: int,
        body: UpdateProductRequest,
        *,
        idempotency_key: str,
    ) -> ApiResponse[WriteResponse[ProductResponse]]:
        """管理员按版本号更新商品信息，并用幂等键保护重复提交。"""
        return self.products.update_product(
            product_id,
            body,
            idempotency_key=idempotency_key,
        )

    def list_addresses(
        self, query: PaginationQuery | None = None
    ) -> ApiResponse[PageResponse[AddressResponse]]:
        """分页查询当前用户的收货地址簿。"""
        return self.addresses.list_addresses(query)

    def create_address(
        self, body: CreateAddressRequest, *, idempotency_key: str
    ) -> ApiResponse[WriteResponse[AddressResponse]]:
        """为当前用户新增收货地址，并用幂等键保护重复提交。"""
        return self.addresses.create_address(body, idempotency_key=idempotency_key)

    def update_address(
        self,
        address_id: int,
        body: UpdateAddressRequest,
        *,
        idempotency_key: str,
    ) -> ApiResponse[WriteResponse[AddressResponse]]:
        """按版本号更新当前用户的收货地址。"""
        return self.addresses.update_address(
            address_id,
            body,
            idempotency_key=idempotency_key,
        )

    def list_orders(
        self, query: OrderListQuery | None = None
    ) -> ApiResponse[PageResponse[OrderResponse]]:
        """分页查询当前用户订单，可按状态、编号、商品名或备注筛选。"""
        return self.orders.list_orders(query)

    def list_admin_orders(
        self, query: OrderListQuery | None = None
    ) -> ApiResponse[PageResponse[OrderResponse]]:
        """管理员分页查询全部订单，可使用订单列表筛选条件。"""
        return self.orders.list_admin_orders(query)

    def get_order(self, order_id: int) -> ApiResponse[OrderResponse]:
        """查询当前用户订单详情及其地址快照、商品明细和版本。"""
        return self.orders.get_order(order_id)

    def create_order(
        self, body: CreateOrderRequest, *, idempotency_key: str
    ) -> ApiResponse[WriteResponse[OrderResponse]]:
        """创建订单并扣减库存，使用幂等键避免重复创建。"""
        return self.orders.create_order(body, idempotency_key=idempotency_key)

    def pay_order(
        self,
        order_id: int,
        body: OrderVersionRequest,
        *,
        idempotency_key: str,
    ) -> ApiResponse[WriteResponse[OrderResponse]]:
        """模拟支付待支付订单，并校验订单版本。"""
        return self.orders.pay_order(
            order_id,
            body,
            idempotency_key=idempotency_key,
        )

    def cancel_order(
        self,
        order_id: int,
        body: OrderVersionRequest,
        *,
        idempotency_key: str,
    ) -> ApiResponse[WriteResponse[OrderResponse]]:
        """取消允许取消的订单，并按业务规则恢复库存。"""
        return self.orders.cancel_order(
            order_id,
            body,
            idempotency_key=idempotency_key,
        )

    def change_order_address(
        self,
        order_id: int,
        body: ChangeOrderAddressRequest,
        *,
        idempotency_key: str,
    ) -> ApiResponse[WriteResponse[OrderResponse]]:
        """修改未发货订单的收货地址，并校验订单版本。"""
        return self.orders.change_order_address(
            order_id,
            body,
            idempotency_key=idempotency_key,
        )

    def ship_order(
        self,
        order_id: int,
        body: ShipOrderRequest,
        *,
        idempotency_key: str,
    ) -> ApiResponse[WriteResponse[OrderResponse]]:
        """管理员登记物流单号并发货。"""
        return self.orders.ship_order(
            order_id,
            body,
            idempotency_key=idempotency_key,
        )

    def list_operations(
        self, query: PaginationQuery | None = None
    ) -> ApiResponse[PageResponse[OperationSummaryResponse]]:
        """分页查询当前用户已成功提交的操作摘要。"""
        return self.operations.list_operations(query)

    def get_operation(
        self, idempotency_key: str
    ) -> ApiResponse[OperationDetailResponse]:
        """按幂等键查询原始操作结果，核实写入是否已提交。"""
        return self.operations.get_operation(idempotency_key)

    def chat(self, message: str) -> ApiResponse[ChatResponse]:
        """将一条聊天消息发送给网站配置的 Agent 空服务。"""
        return self.assistant.chat(message)


__all__ = [
    "API_BASE_URL_ENV",
    "DEFAULT_API_BASE_URL",
    "DEFAULT_TIMEOUT_SECONDS",
    "AddressResponse",
    "AddressFields",
    "AddressSnapshot",
    "ApiResponse",
    "ApiRequest",
    "ApiErrorData",
    "ApiErrorEnvelope",
    "AssistantApi",
    "AuthApi",
    "BusinessApiClient",
    "BusinessApiConnectionError",
    "BusinessApiException",
    "BusinessApiHttpError",
    "BusinessApiProtocolError",
    "BusinessApiTransport",
    "ChatRequest",
    "ChatResponse",
    "ChangeOrderAddressRequest",
    "CreateAddressRequest",
    "CreateOrderRequest",
    "CreateProductRequest",
    "CurrentUserResponse",
    "CsrfResponse",
    "HealthResponse",
    "LoginRequest",
    "LoginResponse",
    "LogoutResponse",
    "OperationDetailResponse",
    "OperationSummaryResponse",
    "OrderItemRequest",
    "OrderItemResponse",
    "OrderListQuery",
    "OrderResponse",
    "OrderStatus",
    "OrderVersionRequest",
    "OrdersApi",
    "PageResponse",
    "PaginationQuery",
    "ProductFields",
    "ProductListQuery",
    "ProductResponse",
    "ProductsApi",
    "ShipOrderRequest",
    "SystemApi",
    "UpdateAddressRequest",
    "UpdateProductRequest",
    "WriteResponse",
    "validate_idempotency_key",
]
