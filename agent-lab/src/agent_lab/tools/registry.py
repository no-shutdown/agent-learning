"""工具目录：收集工具、按 ID 查找及生成描述，不处理会话或执行策略。"""

from collections.abc import Iterable

from . import addresses, operations, orders, products
from .contracts import Tool

ALL_TOOLS = (*orders.TOOLS, *addresses.TOOLS, *products.TOOLS, *operations.TOOLS)


class ToolRegistry:
    """默认收录全部工具；也可由调用方传入工具子集。

    工具集合不是权限凭证。未来 runtime 根据可信身份选择可见工具，
    并在每次执行前检查权限、确认及预算。本类不调用任何业务接口。
    """

    def __init__(self, tools: Iterable[Tool] = ALL_TOOLS) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            if tool.tool_id in self._tools:
                raise ValueError(f"工具 ID 重复：{tool.tool_id}")
            self._tools[tool.tool_id] = tool

    def get(self, tool_id: str) -> Tool:
        """返回已注册的工具；未知 ID 抛出 KeyError，不动态加载函数。"""
        return self._tools[tool_id]

    def definitions(self) -> list[dict]:
        """返回本目录的工具描述；不进行身份判断或授权过滤。"""
        return [tool.definition() for tool in self._tools.values()]
