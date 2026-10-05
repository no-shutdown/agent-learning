# 模型统一协议

主循环只依赖 `models/contracts.py`；每个模型客户端把统一协议适配到实际服务。

```text
loop → ChatModel.generate(ModelRequest) → OllamaClient → Ollama HTTP
loop ← ModelResponse                  ← OllamaClient ← 原始响应
```

## 项目内的数据类型

| 类型 | 主要字段 | 用途 |
|---|---|---|
| Message | role、text、tool_calls、tool_result | 对话历史；工具结果保持对象，不预先序列化为服务端 content |
| ModelRequest | messages、tools | 本轮完整历史和项目工具描述 |
| ModelResponse | text、tool_calls、metadata | 模型的回答、待执行调用及可选元数据 |
| ToolCall | call_id、tool_id、arguments | 已由适配器转换的工具请求；executor 仍负责白名单和业务参数校验 |
| ChatModel | generate(request, timeout_seconds=...) | 主循环唯一调用的模型接口 |
| ModelError | 异常基类 | main 统一处理的模型错误；具体适配器异常继承它 |

这些类型检查必要结构和 JSON 可序列化性。请求工具描述继续使用项目原有 tool_id/description/parameters，不包含 Ollama 的 function 包装。元数据不参与主循环决策。

示例：

```python
from agent_lab.models import Message, ModelRequest

request = ModelRequest(
    messages=[Message("system", "系统规则"), Message("user", "查询订单12")],
    tools=registry.definitions(),
)
response = model.generate(request, timeout_seconds=30)
# response.text
# response.tool_calls → executor.execute(...)
```

调用工具后，loop 追加：

```python
Message("assistant", response.text, response.tool_calls)
Message("tool", tool_result=execution_result)
```

确认暂停、恢复、取消和下一轮聊天均保存相同的 Message 类型。HTTP 客户端不能自行提交这份历史。

## OllamaClient 的职责

- 将统一消息转换成 Ollama 的 role/content/tool_calls 等字段。
- 将项目工具描述包装成 Ollama 原生 function tools。
- 发送 /api/chat 请求，记录脱敏后的实际请求与响应日志。
- 验证原始响应，转换成 ModelResponse；不把 thinking 放进统一历史。
- 保留原生调用编号；没有编号时生成 UUID 编号。回填工具结果时编码 JSON，并保留工具名和调用关联编号。

chat / chat_with_tool_definitions 是保留的 Ollama 低层接口，便于单独实验。loop 和 main 的业务流程使用 generate，不读取原始 message/function/content 字段。

## 增加其他客户端

实现 generate 接口，把请求和响应转换为上述统一类型，并把服务错误转成 ModelError 子类。在 main 的组装入口选择并注入新客户端即可；无需为供应商在 loop 加分支。

当前只实现 Ollama 适配器；没有新增其他服务依赖或供应商配置。统一协议目前支持文本与工具调用，不包含图片、流式事件或供应商专用推理状态；未来支持这些能力时需明确扩展协议，不能直接把供应商原始结构塞回 loop。
