# 运行日志

启动 Agent 的 `make run` 后，日志同时输出到终端和 `agent-lab/runs/logs/agent.jsonl`。每行是一个 JSON 事件；默认文件不依赖启动时的工作目录。可通过 `.env` 的 `AGENT_LOG_DIR` 指定其他目录。

在 agent-lab 目录另开终端：

```sh
tail -f runs/logs/agent.jsonl
```

查看已有文件的缩进格式（Python 3.13）：

```sh
.venv/bin/python -m json.tool --json-lines runs/logs/agent.jsonl
```

## 记录哪些步骤

| event | 内容 |
|---|---|
| request.request | 用户输入或确认选择、路由、对话编号与请求编号 |
| identity.verified | 业务 API 身份核实通过及管理员标记，不记录会话凭据 |
| loop.started / loop.resumed | 提示文本版本、循环预算或待恢复工具编号 |
| llm.request | 每一次实际 Ollama 请求体：model、完整 messages、tools、options、stream 等，以及超时 |
| llm.response | 模型回答、原生 tool_calls、模型返回的 token 数/结束原因等元数据（如果有） |
| tool.request | 工具名称、call_id、具体参数、剩余超时 |
| tool.response | 执行器返回的真实结果，包括成功、拒绝、等待确认、结果未知及业务幂等键 |
| confirmation.received | 页面确认或取消选择 |
| confirmation.request / confirmation.response | 程序对原工具调用的确认；成功返回 null，表示确认动作无返回值 |
| loop.finished | 停止状态、模型/工具调用次数与提示版本 |
| request.replayed | 命中请求缓存，没有重新调用模型或工具 |
| request.response | 最终返回网页的回复或待确认操作 |
| *.error / agent.error | 异常类型、已知错误码和步骤耗时；不输出可能含凭据的原始异常文本 |
| http.response / service.started / service.stopped | HTTP 状态及服务生命周期 |

`llm.request` 在模型适配器发送请求前记录，包含系统提示和回填后的全部历史，不是另拼的一份示意提示。执行器拒绝、缓存返回也会记录 tool.response。业务 HTTP 的认证头、Cookie 和原始响应头不记录；业务调用结果以 executor 返回的结果为准。

## 怎样串起一次任务

- `trace_id`：每次 HTTP 应用请求生成一个服务器编号；客户端重试会有新的 trace_id。
- `conversation_id` / `request_id`：网页生成的编号，便于识别对话及同一请求重试。
- `task_id`：任务开始后生成。后续点击确认恢复时沿用，可以跨 HTTP 请求查到同一任务的工具执行。
- `step_id`：一次调用的 request/response/error 配对编号。
- `call_id`：工具调用编号。elapsed_ms 是这一步的耗时，不包含用户停留在确认页面的时间。

request.request 发生在任务识别前，可能没有 task_id，可用 trace_id 关联后续事件。HTTP 格式检查阶段的拒绝只有状态日志。独立使用模型/执行器模块时不会自动创建文件；需要应用调用 configure_logging，并可用 trace_context 设置关联编号。

## 脱敏、保存与范围

日志记录脱敏副本，不改变发给模型或业务接口的实际内容。密码、Cookie、授权头、密钥、会话与确认令牌等已知字段会被遮盖；tool content 中的嵌套 JSON 也做同样处理。手机号、结构化收件人和详细地址会遮盖。自由文本会处理常见 Bearer、sk- 密钥、password/token 等赋值形式与手机号，不能识别所有自然语言中的隐私；请继续使用模拟数据练习。

不保存模型 thinking/reasoning 隐藏思考字段。模型回复正文和工具调用仍保留。

单个文件达到约 10 MiB 时轮转，保留 5 个历史文件；单条超大事件可能超过该阈值。文件权限为当前用户读写。默认 runs 目录已被 Git 忽略，自定义目录需自行保持不提交。日志写入失败不改变业务执行结果，因此本功能不是可靠审计存储或任务恢复机制。
