"""当前用户地址簿；修改地址簿不会自动修改已有订单的地址快照。"""

from ..clients import AddressesApi
from .contracts import ID, PAGE, VERSION, Tool, obj, string

FIELDS = {
    "recipient": string("收件人", 40),
    "phone": string("演示手机号：1 开头的 11 位数字", 11, pattern=r"1[0-9]{10}"),
    "province": string("省", 30),
    "city": string("市", 30),
    "district": string("区县", 30),
    "detail": string("详细地址", 150),
}

LIST_ADDRESSES = Tool(
    "list_addresses",
    "分页查询当前用户地址簿，返回 ID 和版本；同名地址需澄清。",
    obj(PAGE, ()),
    AddressesApi,
    AddressesApi.list_addresses,
)

CREATE_ADDRESS = Tool(
    "create_address",
    "新增当前用户的收货地址。必须确认。",
    obj(FIELDS),
    AddressesApi,
    AddressesApi.create_address,
    "write",
)

UPDATE_ADDRESS = Tool(
    "update_address",
    "完整更新地址簿条目，不影响已有订单地址快照。必须确认。",
    obj({"address_id": ID, **FIELDS, "version": VERSION}),
    AddressesApi,
    AddressesApi.update_address,
    "write",
    "address_id",
)

TOOLS = (
    LIST_ADDRESSES,
    CREATE_ADDRESS,
    UPDATE_ADDRESS,
)
