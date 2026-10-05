# 原生工具调用

系统提示描述业务边界和行为要求；工具定义通过请求的 `tools` 参数传递。
`load_prompt()` 不再接收工具列表参数，版本只计算系统提示文本。实验记录需要另外保存工具定义及模型配置，不能把提示文本版本当作整次实验的完整版本。

```python
from agent_lab.prompts.loader import load_prompt
from agent_lab.tools import GET_ORDER, ToolRegistry

# model 是已按应用配置创建的 OllamaClient；此处只演示一个查询工具。
registry = ToolRegistry([GET_ORDER])
response = model.chat_with_tool_definitions(
    [
        {"role": "system", "content": load_prompt().text},
        {"role": "user", "content": "请查询订单 ID 12"},
    ],
    tool_definitions=registry.definitions(),
)
# response["message"]["tool_calls"] 是待检查、待执行的请求，不能当作已执行结果。
```

模型客户端把内部的 `tool_id/description/parameters` 转换成
`type=function, function={name, description, parameters}`。内部权限标记仍由 runtime 使用，不是模型授权证明。
原生工具定义的参数 JSON Schema 由业务工具维护；服务端不会自动发现网站接口。

现有循环保留工具调用历史，把执行器结果 JSON 放进
`{"role": "tool", "tool_name": "get_order", "content": "..."}`，再请求模型继续。
普通回复从 `message.content` 读取，仅 `message.tool_calls` 触发执行器。
正文即使包含旧的 `role/type/data` JSON，也只是文本，不会执行。
`ToolExecutor` 已实现，测试包含真实执行器与模拟 HTTP 的接入；HTTP `/chat` 仍是占位回复。

## Ollama 内部怎样处理 tools

2026-10-05 核对本地 `/api/version` 为 **0.35.0**。本地 `qwen3.5:9b`
的 `/api/show` 声明支持 tools；Modelfile 指定 `RENDERER qwen3.5`、
`PARSER qwen3.5`，虽然 TEMPLATE 字段只显示 `{{ .Prompt }}`，仍会使用专用渲染器。

处理过程是：结构化 messages 和 tools → 模型专用渲染 → 分词得到 token →
模型推理 → 模型专用输出解析 → HTTP JSON 中的 content、thinking、tool_calls。

在这个版本的 [Qwen3.5 渲染器](https://github.com/ollama/ollama/blob/v0.35.0/model/renderers/qwen35.go) 中，
工具定义被序列化后放进 system 区域的 `<tools>` 块，随后加入工具调用格式指令及应用提供的系统提示。
再组织用户消息、历史调用与工具结果。格式中的特殊标记配合模型训练时的约定使用。

[Qwen3.5 解析器](https://github.com/ollama/ollama/blob/v0.35.0/model/parsers/qwen35.go)
分离思考部分，并委托工具解析器处理函数调用标记。API 最终暴露结构化的 `tool_calls`，
应用不必自行解析模型内部的 XML 风格标记。

这不是把 Python 函数或 HTTP 接口上传给模型执行。它仍然是通过模型输入描述能力，
由模型生成调用意图，再由应用验证和执行；工具描述也占用上下文。
不同模型/版本可使用不同模板、渲染器、标记与解析器，不能把 Qwen3.5 的格式推广到全部模型。
原生 API 统一了应用层交互，不保证每个参数都合法，更不替代权限与确认机制。

参考：[Ollama 官方工具调用文档](https://docs.ollama.com/capabilities/tool-calling)。
