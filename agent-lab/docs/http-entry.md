# HTTP 入口与网站接入

`main.py` 负责配置注入、OllamaClient / 业务会话 / 工具目录 / ToolExecutor 的组装，以及 HTTP 请求和内存会话。模型循环仍由 `runtime/loop.py` 管理，工具授权与执行仍由 `runtime/executor.py` 管理。

## 启动与使用

1. 打开 Ollama App，准备 `.env` 中 MODEL_NAME 指定的模型（默认 qwen3.5:9b）。
2. business-demo 中执行 `make run`，agent-lab 中执行 `make run`；父目录网站启动器也兼容。
3. 登录业务网站，打开 AI 助手。先试“查询我的订单”，然后追问某笔订单。涉及写入时核对确认卡片后点击确认或取消。

Agent 仅监听 127.0.0.1。手机仍访问业务网站，由网站转发，无需开放 Agent 端口。`GET /health` 仅说明 HTTP 入口存活，不保证模型或业务服务可用。

## 请求契约

网站 `/api/v1/assistant/chat` → Agent `POST /chat`：

```json
{"conversation_id":"page1","request_id":"r1","message":"查询我的订单"}
```

网站 `/api/v1/assistant/confirm` → Agent `POST /confirm`：

```json
{"conversation_id":"page1","request_id":"r2","confirmation_id":"服务返回的令牌","accept":true}
```

两种请求均由网站设置 `X-Business-Session`，来源是已登录且通过 CSRF 检查的 Django 请求。正文不接受用户名、角色、工具参数或历史消息。Agent 通过业务 `/me` 核实身份，普通用户工具目录不含管理员工具；executor 和业务后端仍逐次检查权限。会话凭据不放入模型消息。

当前会话绑定依赖此业务网站的默认 Django 数据库 session 和 sessionid Cookie；更换会话后端或 Cookie 名时需要适配。浏览器直接跨站请求 Agent 被拒绝，Agent 不提供 CORS。该入口用于可信本机开发环境；本机程序持有有效业务会话就代表该用户，不是面向公网的委派认证方案。

## 回复和确认

普通结果包含 `reply`、`status` 和 `implemented:true`。status 可能为 completed、confirmation_required、cancelled、budget_exhausted 或 error。

等待确认时额外包含 `confirmation_id` 和 `confirmation`。网页以纯文本展示具体工具、参数、影响及有效期；模型声称用户确认、用户输入“确认”均不能触发授权。程序确认后，resume_loop 先执行服务端保存的原始请求，再回填工具结果继续模型循环。后续写入仍需分别确认。

确认默认有效 300 秒，过期后取消并重新查询。取消会停止该批尚未执行的工具请求，已经执行的查询或操作不会回滚。

## 本地状态与限制

- 会话按业务 session 与 conversation_id 隔离，同一会话同时只处理一条请求。
- 每个新聊天任务创建 executor；确认恢复复用原执行器和原业务幂等键。
- 同一 request_id 重试会返回缓存结果，改变内容会被拒绝；同一任务的工具去重另由 executor 保证。
- 默认最多 64 个会话，闲置 30 分钟清理，每会话最多 50 个请求；历史超过 80 条后要求新建对话。
- 模型/循环活动时限取 MODEL_TIMEOUT_SECONDS（默认 120 秒），等待用户确认不计入；恢复沿用剩余模型/工具调用次数。业务请求仍受自己的超时约束。
- 业务网站默认代理等待 150 秒；提高模型时限时也应相应提高 AGENT_TIMEOUT_SECONDS。超时不等于业务事务被取消。
- 历史、确认、请求缓存只在进程内存；刷新页面创建新对话，重启丢失状态。还未实现跨重启恢复、持久化 tracing 或 evals。

模型在写入后失败时，入口明确提示核实操作记录，不宣称操作失败。请先在网站确认业务状态；不要用新 request_id 或刷新页面绕过未知结果。当前请求缓存不能提供跨进程的幂等保证。

Agent 显式设置 `MODEL_CONTEXT_TOKENS=16384`（可配置范围 1024～131072），避免本机 Ollama 默认 4096 窗口在回填工具结果后截断回复。增大会增加内存占用；这不是自动压缩历史或永久记忆，长对话仍需开始新会话。
