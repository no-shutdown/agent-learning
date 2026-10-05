# 本地业务 Agent 学习环境

这里有两个学习项目：订单业务网站和逐步实现的 Python Agent。模型运行、管理与独立聊天统一使用 Ollama 官方 App。原有桌面学习路线与笔记未修改。

## 日常启动

需要使用模型时，先打开 **Ollama App**，在 App 中选择 `qwen3.5:9b` 直接聊天；Agent 通过同一 Ollama 服务的 HTTP API 调用模型。

双击本目录的 **启动网站.command**，启动业务网站和 Agent 服务，在浏览器打开 http://127.0.0.1:8000 。保持启动窗口打开，按 Ctrl+C 停止由该窗口启动的服务。已有服务不会重复启动，也不会被新窗口停止。代码更新后需先在原启动窗口停止旧服务，再重新启动并刷新网页；启动器不会自动重启旧进程。

| 用途 | 账户 | 密码 |
|---|---|---|
| 普通用户 | user01（另有 user02～user49） | demo12345 |
| 管理员 | admin | demo12345 |

这些是专用的本机演示账户，不是真实凭据。服务只监听 127.0.0.1。

- 网站：8000，登录后可浏览商品、下单、模拟支付、取消、改地址。
- Agent 服务：8001，网站 AI 助手已接入模型和业务工具，写入通过页面按钮确认。
- 本地模型：11434，单独启动，不影响网站独立使用。

## 模型使用

当前已安装 `qwen3.5:9b`（Q4_K_M，模型文件约 6.59 GB）。模型已下载与模型已加载到内存是两个不同状态；请求时可以自动加载模型。

- 服务地址：`http://127.0.0.1:11434`。
- 对话接口：`POST /api/chat`，请求中的 `model` 填写 `qwen3.5:9b`。
- 已安装模型：`GET /api/tags`。
- 当前加载模型：`GET /api/ps`。
- `agent-lab` 直接调用 Ollama，无需额外的模型服务封装。模型调用、工具循环、执行器及网站入口已接通；提示评估与运行追踪仍待练习。

检查服务和模型：

```sh
curl --noproxy '*' http://127.0.0.1:11434/api/version
ollama list
ollama ps
```

发送一次对话请求：

```sh
curl --noproxy '*' http://127.0.0.1:11434/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3.5:9b","messages":[{"role":"user","content":"你好"}],"stream":false,"think":false}'
```

回答位于返回 JSON 的 `message.content`。`think: false` 关闭本次请求的思考模式。`ollama stop qwen3.5:9b` 可释放模型运行内存，保留模型文件。

Ollama App 与命令行服务使用同一个默认端口，无需重复启动。旧脚本中的上下文和并发环境变量不会自动成为 App 的配置；[模型实测](model-check/REPORT.md) 记录的是测试当时的参数与结果。

## 已停用的旧入口

日常使用不再需要 Docker 或下列旧入口。文件暂时保留，未删除：

| 文件或目录 | 当前状态 |
|---|---|
| `启动模型.command` | 旧的命令行 Ollama 启动方式，改用 App |
| `启动模型管理.command` | 旧的 Open WebUI 启动入口，不再使用；执行它仍会启动容器 |
| `compose.models.yaml` | 旧的 Open WebUI 部署配置 |
| `docs/open-webui-models.png` | 之前部署 Open WebUI 时的验证截图 |

Open WebUI 容器已停止并关闭自动重启，数据卷 `agent-learning-models_open-webui-data` 保留。`启动网站.command` 仍是业务网站与 Agent 服务的有效启动入口。

## 项目入口

- [网站说明](business-demo/README.md)：启动、重置、测试和业务规则。
- [HTTP 接口](business-demo/docs/API.md)：后续 Agent 接入契约。
- [固定场景](business-demo/docs/SCENARIOS.md)：边界数据和预期业务结果。
- [Agent 学习项目](agent-lab/README.md)：哪些已准备、哪些由你练习。
- [模型实测](model-check/REPORT.md)：测试范围、复跑方式和实测记录。

`model-check/` 只是模型选型辅助材料，不是额外的应用，也不会被网站或 Agent 导入。

## 重置到同一基线

先停止正在进行的写操作，在终端执行：

```sh
cd /Users/colin/code/my/agent-learning/business-demo
make reset
```

这会删除该 Demo 数据库中的用户、会话、订单、地址和操作记录，重新生成 50 个用户、30 个商品、100 个地址、500 笔订单。重置后重新登录。它不删除代码、Agent 练习成果或模型。

## 使用约定

先动手，再求提示；每次只练一个能力。用固定输入比较修改前后效果，保留失败，不把所有失败归因于提示词。提示、工具与执行循环已有实现，可继续通过固定用例练习改进；评估与运行追踪尚未实现。

所有业务数据均为虚构；支付、退款和物流为本地模拟。当前是完整的本地业务闭环，不包含真实支付、短信、外部物流、公开注册或生产部署。

## 版本管理

本目录统一管理 `business-demo` 和 `agent-lab` 的源码，提交与推送在 `agent-learning` 根目录进行。两个项目仍使用各自的虚拟环境及启动命令。虚拟环境、本地数据库、密钥和 IDE 配置不纳入版本库。

整合前的独立 Git 历史在本机 `.git/local-repository-history/` 中保留，不随远程推送。
