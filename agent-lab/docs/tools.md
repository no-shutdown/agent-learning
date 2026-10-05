# 业务工具

工具层已实现，HTTP `/chat` 仍为占位服务。模型客户端和可注入执行器的循环已实现，工具执行器已实现，HTTP 接入及确认交互尚未实现。

## 职责

- `contracts.py`：`Tool` 结构、参数契约及校验、底层客户端适配调用。
- `orders.py`、`addresses.py`、`products.py`、`operations.py`：具体工具定义。
- `registry.py`：汇总、按 ID 查找、导出描述；不维护会话，不调用接口，不判断身份或执行工具。
- `__init__.py`：统一导出公共工具、工具集合和注册表。

`runtime/executor.py` 已实现身份、权限、确认、幂等及结果转换，详见 [执行器说明](executor.md)。
这些职责不属于注册表，工具模块仍只负责契约与 HTTP 调用适配。

## 已有工具

| 模块 | 工具 ID |
| --- | --- |
| orders | list_orders、get_order、create_order、pay_order、cancel_order、change_order_address |
| orders（需管理员） | list_admin_orders、ship_order |
| addresses | list_addresses、create_address、update_address |
| products | list_products、get_product |
| products（需管理员） | list_admin_products、create_product、update_product |
| operations | list_operations、get_operation |

公共具名对象使用对应大写名称，例如 `LIST_ORDERS`；`ALL_TOOLS` 包含全部 18 个定义。
`routing.py` 未实现，未作为可用工具导出。

## 查看和查找工具

在 agent-lab 目录使用 `PYTHONPATH=src .venv/bin/python`：

```python
from agent_lab.tools import LIST_ORDERS, ToolRegistry

registry = ToolRegistry()  # 不需要登录、transport 或网络
all_definitions = registry.definitions()
order_tool = registry.get("list_orders")  # 未知 ID 抛出 KeyError
order_tool.validate({"page_size": 5})

# 也支持调用方选定的工具集合，重复 ID 会报错。
read_example = ToolRegistry([LIST_ORDERS])
```

`definitions()` 返回当前目录中所有工具描述，包括 `requires_admin` 和
`requires_confirmation` 等声明。这些字段是元数据，不代表完成了授权。
默认目录包含管理员工具，不能把默认全量描述误认为当前用户的授权工具列表。
调用方应依据可信身份选定可见工具；执行器在实际执行时重新检查身份与权限。

## 客户端与底层适配

`clients/__init__.py` 直接导出 `OrdersApi` 等模块客户端、传输层和契约，
没有重复转发端点方法的聚合类。一个用户的各模块共享一个 `BusinessApiTransport`，
不同用户不能共享或在操作中切换会话。Cookie、CSRF 及单请求超时仍由传输层管理。

`Tool.invoke(transport, arguments, key)` 是给执行器及底层测试使用的适配方法，
不是接收模型请求的入口。它校验参数，将资源 ID、查询参数或请求体传给对应客户端，
并原样返回 `ApiResponse`；客户端异常原样抛出，不自动重试。
写工具必须由调用方提供有效幂等键，它不会生成键，也不负责确认流程。
模型请求必须经过 `ToolExecutor.execute`，不应直接接到 `invoke`。

响应中的业务数据在 `ApiResponse.data` 中，HTTP 响应头不应进入模型上下文。
成功写入的业务数据为 `{data: 业务对象, replayed: 布尔值}`；列表为
`count/page/page_size/results`。执行器负责校验响应、生成 `success/error/unknown` 执行结果，循环关联调用编号并将数据序列化到原生 tool 消息中，尤其不能将写入超时简单视为失败后重发。
`get_operation` 接收原操作编号，查询不到记录不证明没有正在执行的请求。

## 校验和测试

工具参数采用 JSON Schema 描述，`contracts.py` 只实现本项目使用的约束子集。
它拒绝未知字段、缺失字段、布尔值冒充整数等；工具层搜索词限制为 200 字。
业务后端继续保证所有权、版本、库存、状态转换及写入幂等，不依赖提示词。

运行 `make test`，验证注册表、参数契约及所有工具对应的 HTTP 请求。
测试使用模拟传输，不修改业务数据库，不调用模型。
执行器测试另行验证 runtime 的权限、确认、去重及结果状态。

模型工具列表通过原生 `tools` 参数传递，不注入系统提示。具体消息格式及 Ollama 内部处理见 [原生工具调用](native-tool-calling.md)。
