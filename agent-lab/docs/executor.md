# 工具执行器

## 职责拆分

`loop.py` 组织统一 Message、调用模型统一 generate 接口、接收统一 ToolCall，管理整次任务的模型/工具次数及总时限，决定何时回答或暂停。

`executor.py` 提供 `ToolExecutor`：工具白名单、参数校验、身份和管理员权限、可信确认、调用去重、业务幂等键、单次执行次数和超时控制、业务调用及结果转换。执行器不调用模型、不拼历史、不选择下一步。

`runtime/contracts.py` 保存执行器接口协议、结果状态和结果校验；ToolCall 定义在 models/contracts.py，并由 runtime/contracts.py 兼容导出。loop 调用共享校验器检查结果是否与请求匹配，这是消息接入检查，不是再次执行业务规则。

`tools/registry.py` 仍只查找工具和描述。业务后端仍独立验证对象所有权、订单状态、版本、库存及幂等冲突。

## 建立单用户、单任务执行器

```python
from agent_lab.runtime.executor import ToolExecutor
from agent_lab.runtime.loop import run_loop
from agent_lab.tools import GET_ORDER, PAY_ORDER, ToolRegistry

# transport 是已登录的当前用户会话；verified_username 来自可信登录上下文。
# model 已使用应用配置创建。
registry = ToolRegistry([GET_ORDER, PAY_ORDER])
executor = ToolExecutor(transport, registry, username=verified_username)
result = run_loop(
    "查询订单 12", model=model, executor=executor, registry=registry,
)
```

每个任务创建独立 executor，默认最多接收 16 次 execute（包括拒绝、结果重放及等待确认）。
loop 的整任务次数限制继续保留；两者保护的入口不同，单独调用 executor 也不能无限执行。
同一用户各客户端可以共享 transport，不同用户不能共享会话。每次执行会向业务服务核实当前身份；身份变化、管理员权限撤销都会拒绝操作。注册表应由程序按可信身份选择，不能让模型提供白名单。

## 写入确认

```python
pending = executor.execute(
    call_id="pay_1", tool_id="pay_order",
    arguments={"order_id": 12, "version": 3}, timeout_seconds=5,
)
# pending.status == confirmation_required；到这里没有发送写请求。
# UI 展示 pending["confirmation"] 中的具体工具、参数和影响。
# 只有服务器验证用户身份及对应确认事件后，才能调用：
executor.confirm("pay_1", username=verified_username)

result = executor.execute(
    call_id="pay_1", tool_id="pay_order",
    arguments={"order_id": 12, "version": 3}, timeout_seconds=5,
)
```

`confirm` 是可信应用接口，不是模型工具，不是解析到用户文字“确认”就可调用。
确认记录绑定当前任务的用户、工具和完整参数，默认有效 300 秒。改变相同 call_id 的参数会报 call_conflict；新编号的新参数会要求新确认。确认过期需重新核实业务状态并启动新任务。

网站已提供确认/取消按钮，HTTP 入口保存 pending_calls 和 pending_confirmation。收到可信确认后先调用 executor.confirm，再用 resume_loop 执行原参数并接续模型。多个写请求逐个确认；取消时未执行请求不会继续。详见 [HTTP 入口](http-entry.md)。

## 重复请求及结果

所有结果含 `call_id/tool_id/status/result/error`，等待确认时另含 `confirmation`。

- 查询成功：`result` 为业务 JSON，不带响应头。
- 写入成功：`result` 为 `{operation_key, response: {data, replayed}}`。
- 业务拒绝、参数/权限错误：`status=error`，提供错误码与说明。
- 已尝试写入后超时、连接中断、HTTP 408/5xx 或不可信响应：`status=unknown`，附原 operation_key，不断言写入失败。
- 确认前的身份查询失败：`status=error`，未尝试业务写入。

相同 call_id 和参数返回原已完成结果，不重新发请求；相同 ID 改参数会拒绝。
同一任务内相同工具和参数的写请求，即使更换 call_id，也复用原记录和幂等键。
这是有意限制：确实要再次创建一笔相同订单时，应启动独立任务并重新确认。
结果为 unknown 时不会重发写入；用 `get_operation` 查询原 operation_key。
查询不到记录不证明没有尚在处理的请求。不要通过重新创建任务绕过未知结果。

底层业务请求受同一个会话锁保护，避免身份检查和写入之间切换账号。默认 socket 超时不变；本次身份、CSRF 和业务请求使用剩余预算。每次发请求前与响应后检查截止时间；同步 HTTP 的 socket 超时不是强制取消服务器事务，也不承诺面对持续慢速传输时的严格墙钟截止。

## 当前范围

状态只在内存中保存，适合本地学习；未实现跨进程/重启恢复、持久化审计或通用工作流。意外内部错误对模型只返回 internal_error；写入可能已发生时保守返回 unknown。业务响应检查包含基础分页/实体格式、重放标记及目标匹配，不是完整业务 DTO 校验。

`make test` 覆盖权限、确认绑定及过期、管理员撤权、重复/并发写入、异常结果、超时传递，以及 loop 调用真实 ToolExecutor 的集成。使用模拟 HTTP，不修改本地业务数据库。
