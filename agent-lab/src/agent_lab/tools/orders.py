"""订单工具：查询、创建、模拟支付、取消、改地址及管理员发货。"""

from ..clients import OrdersApi
from .contracts import ID, SEARCH, VERSION, Tool, integer, obj, string, unique_items

QUERY = obj(
    {
        **SEARCH,
        "status": string("订单状态", 20, enum=["pending_payment", "paid", "shipped", "cancelled"]),
    },
    (),
)
ACTION = {"order_id": ID, "version": VERSION}

LIST_ORDERS = Tool(
    "list_orders",
    "分页查询当前用户订单；支持编号、商品名、备注和状态筛选。",
    QUERY,
    OrdersApi,
    OrdersApi.list_orders,
)

LIST_ADMIN_ORDERS = Tool(
    "list_admin_orders",
    "管理员分页查询所有用户订单；返回版本号用于发货。",
    QUERY,
    OrdersApi,
    OrdersApi.list_admin_orders,
    admin=True,
)

GET_ORDER = Tool(
    "get_order",
    "查询当前用户订单详情、商品明细、地址快照和版本。",
    obj({"order_id": ID}),
    OrdersApi,
    OrdersApi.get_order,
    "detail",
    "order_id",
)

CREATE_ORDER = Tool(
    "create_order",
    "创建订单并扣库存。先查询商品及地址；必须由用户确认。",
    obj(
        {
            "address_id": ID,
            "items": {
                "type": "array",
                "minItems": 1,
                "maxItems": 20,
                "items": obj({"product_id": ID, "quantity": integer("购买数量", maximum=99)}),
            },
            "note": string("订单备注", 300, required=False),
        },
        ("address_id", "items"),
    ),
    OrdersApi,
    OrdersApi.create_order,
    "write",
    extra_validation=unique_items,
)

PAY_ORDER = Tool(
    "pay_order",
    "模拟支付待支付订单，不产生真实付款。必须确认。",
    obj(ACTION),
    OrdersApi,
    OrdersApi.pay_order,
    "write",
    "order_id",
)

CANCEL_ORDER = Tool(
    "cancel_order",
    "取消待支付或待发货订单，恢复库存；已发货或已取消不可操作。必须确认。",
    obj(ACTION),
    OrdersApi,
    OrdersApi.cancel_order,
    "write",
    "order_id",
)

CHANGE_ORDER_ADDRESS = Tool(
    "change_order_address",
    "修改待支付或待发货订单的地址快照；使用当前用户地址簿 ID。必须确认。",
    obj({**ACTION, "address_id": ID}),
    OrdersApi,
    OrdersApi.change_order_address,
    "write",
    "order_id",
)

SHIP_ORDER = Tool(
    "ship_order",
    "管理员为待发货订单登记物流单号并发货。必须确认。",
    obj({**ACTION, "tracking_no": string("物流单号", 60)}),
    OrdersApi,
    OrdersApi.ship_order,
    "write",
    "order_id",
    admin=True,
)

TOOLS = (
    LIST_ORDERS,
    LIST_ADMIN_ORDERS,
    GET_ORDER,
    CREATE_ORDER,
    PAY_ORDER,
    CANCEL_ORDER,
    CHANGE_ORDER_ADDRESS,
    SHIP_ORDER,
)
