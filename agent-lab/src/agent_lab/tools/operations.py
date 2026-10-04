"""查询已提交的写入，用于核实结果不明的操作。"""

from ..clients import OperationsApi
from .contracts import PAGE, Tool, obj, string


LIST_OPERATIONS = Tool(
    "list_operations",
    "分页查询当前用户已成功提交的操作摘要。",
    obj(PAGE, ()),
    OperationsApi,
    OperationsApi.list_operations,
)

GET_OPERATION = Tool(
    "get_operation",
    "用程序提供的原操作编号核实写入；未找到不代表请求最终失败，不要换键重试。",
    obj({"idempotency_key": string("原操作编号，不是 call_id", 100, pattern=r"[A-Za-z0-9._:-]+")}),
    OperationsApi,
    OperationsApi.get_operation,
    "detail",
    "idempotency_key",
)

TOOLS = (
    LIST_OPERATIONS,
    GET_OPERATION,
)
