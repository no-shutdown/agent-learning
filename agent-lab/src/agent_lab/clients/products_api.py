"""商品查询和管理员商品维护 API。"""

from typing import NotRequired, TypedDict, cast

from .pojo import ApiRequest, ApiResponse, PageResponse, PaginationQuery, WriteResponse
from .transport import BusinessApiTransport


class ProductListQuery(PaginationQuery):
    q: NotRequired[str]


class ProductResponse(TypedDict):
    id: int
    name: str
    category: str
    description: str
    price: str
    stock: int
    active: bool
    version: int


class ProductFields(TypedDict):
    name: str
    category: str
    description: str
    price: str
    stock: int
    active: bool


class CreateProductRequest(ProductFields):
    pass


class UpdateProductRequest(ProductFields):
    version: int


class ProductsApi:
    """提供上架商品查询和管理员商品维护接口。"""

    def __init__(self, transport: BusinessApiTransport) -> None:
        self._transport = transport

    def list_products(
        self, query: ProductListQuery | None = None
    ) -> ApiResponse[PageResponse[ProductResponse]]:
        """分页查询上架商品；可用 q 按商品名称搜索。"""
        return cast(
            ApiResponse[PageResponse[ProductResponse]],
            self._transport.send(ApiRequest("GET", "products", query=query)),
        )

    def get_product(self, product_id: int) -> ApiResponse[ProductResponse]:
        """查询指定上架商品的详情。"""
        return cast(
            ApiResponse[ProductResponse],
            self._transport.send(
                ApiRequest("GET", f"products/{self._path_id(product_id)}")
            ),
        )

    def list_admin_products(
        self, query: ProductListQuery | None = None
    ) -> ApiResponse[PageResponse[ProductResponse]]:
        """管理员分页查询全部商品，包括已下架商品。"""
        return cast(
            ApiResponse[PageResponse[ProductResponse]],
            self._transport.send(ApiRequest("GET", "manage/products", query=query)),
        )

    def create_product(
        self, body: CreateProductRequest, *, idempotency_key: str
    ) -> ApiResponse[WriteResponse[ProductResponse]]:
        """管理员创建商品；每个逻辑写入必须提供唯一幂等键。"""
        return cast(
            ApiResponse[WriteResponse[ProductResponse]],
            self._transport.send(
                ApiRequest(
                    "POST",
                    "manage/products",
                    body=body,
                    requires_csrf=True,
                    idempotency_key=idempotency_key,
                )
            ),
        )

    def update_product(
        self,
        product_id: int,
        body: UpdateProductRequest,
        *,
        idempotency_key: str,
    ) -> ApiResponse[WriteResponse[ProductResponse]]:
        """管理员按商品版本更新商品信息，并用幂等键防止重复提交。"""
        return cast(
            ApiResponse[WriteResponse[ProductResponse]],
            self._transport.send(
                ApiRequest(
                    "PUT",
                    f"manage/products/{self._path_id(product_id)}",
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
