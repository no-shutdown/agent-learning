"""商品查询及管理员商品维护。"""

from ..clients import ProductsApi
from .contracts import ID, SEARCH, VERSION, Tool, integer, obj, positive_price, string

FIELDS = {
    "name": string("商品名称", 100),
    "category": string("分类", 30),
    "description": string("商品描述", 1000, required=False),
    "price": string(
        "价格字符串，0.01～99999999.99，最多两位小数",
        11,
        pattern=r"(?:0|[1-9][0-9]{0,7})(?:\.[0-9]{1,2})?",
    ),
    "stock": integer("库存", minimum=0, maximum=1_000_000),
    "active": {"type": "boolean", "description": "是否上架"},
}

LIST_PRODUCTS = Tool(
    "list_products",
    "分页搜索上架商品，返回价格、库存和 ID。",
    obj(SEARCH, ()),
    ProductsApi,
    ProductsApi.list_products,
)

GET_PRODUCT = Tool(
    "get_product",
    "查询指定上架商品详情。",
    obj({"product_id": ID}),
    ProductsApi,
    ProductsApi.get_product,
    "detail",
    "product_id",
)

LIST_ADMIN_PRODUCTS = Tool(
    "list_admin_products",
    "管理员分页查询全部商品，包括下架商品。",
    obj(SEARCH, ()),
    ProductsApi,
    ProductsApi.list_admin_products,
    admin=True,
)

CREATE_PRODUCT = Tool(
    "create_product",
    "管理员创建商品。必须确认。",
    obj(FIELDS),
    ProductsApi,
    ProductsApi.create_product,
    "write",
    admin=True,
    extra_validation=positive_price,
)

UPDATE_PRODUCT = Tool(
    "update_product",
    "管理员完整更新商品；先查最新版本。必须确认。",
    obj({"product_id": ID, **FIELDS, "version": VERSION}),
    ProductsApi,
    ProductsApi.update_product,
    "write",
    "product_id",
    admin=True,
    extra_validation=positive_price,
)

TOOLS = (
    LIST_PRODUCTS,
    GET_PRODUCT,
    LIST_ADMIN_PRODUCTS,
    CREATE_PRODUCT,
    UPDATE_PRODUCT,
)
