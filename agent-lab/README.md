# Agent Lab：学习项目骨架

以 LLM 选择工具、程序受控执行、真实结果反馈的循环为主线。使用 Python 标准库保留可运行的 HTTP 空服务；新增模块均为职责占位，未实现 Agent。

## 启动

```sh
cd /Users/colin/code/my/agent-learning/agent-lab
make run
```

默认监听 `127.0.0.1:8001`。GET `/health` 返回服务状态；POST `/chat` 接受 `{"message":"你好"}`，校验输入后返回固定的“Agent 尚未实现”。网站 AI 助手面板和父目录的启动网站脚本保持兼容。

重建虚拟环境用 `make setup`；`make check` 检查 src 和 evals 中 Python 文件的语法。当前没有第三方运行依赖。`pyproject.toml` 提供项目、打包和 Ruff 配置，不要求现在安装框架或 SDK。

可复制 `.env.example` 为 `.env`；`make run` 与父目录启动器会加载它。当前只使用 `AGENT_PORT`，其他变量仅供练习参考。Ollama 由 App 独立启动，默认 API 地址为 `http://127.0.0.1:11434`。

## 模型接入方式

由 Ollama App 在本机运行模型并提供 HTTP API。后续在 `src/agent_lab/models/ollama.py` 中直接调用 `http://127.0.0.1:11434/api/chat`，请求中指定模型 `qwen3.5:9b`。该客户端目前仍是空模块。

旧的独立 `model-service` 管理项目已删除。Agent 不依赖该项目、Open WebUI 或 Docker；业务操作仍通过 business-demo 的 HTTP API 执行。

## 目录

```text
src/
├── main.py                   # 兼容旧启动命令，转发到包入口
└── agent_lab/
    ├── __init__.py
    ├── main.py               # 已有的最小 HTTP 服务
    ├── config.py             # 配置读取（待实现）
    ├── schemas.py            # 输入输出与参数校验（待实现）
    ├── runtime/
    │   ├── loop.py           # LLM 决策与工具结果反馈循环（待实现）
    │   ├── context.py        # 本轮消息、提示与工具上下文（待实现）
    │   ├── state.py          # 任务及待确认操作状态（待实现）
    │   ├── executor.py       # 所有工具调用的校验与执行入口（待实现）
    │   ├── limits.py         # 调用预算、超时和停止条件（待实现）
    │   └── tracing.py        # 运行与工具调用记录（待实现）
    ├── models/
    │   └── ollama.py         # 模型 API 客户端（待实现）
    ├── tools/
    │   ├── registry.py       # 工具定义及固定映射（待实现）
    │   ├── orders.py         # 订单工具（待实现）
    │   └── routing.py        # 未来可选的分类或分派工具（未注册）
    ├── clients/
    │   └── business_api.py   # business-demo v1 typed HTTP client
    └── prompts/
        ├── agent.md          # 空白主提示文件
        └── loader.py         # 模板加载与参数化（待实现）
tests/                       # 程序测试，尚无用例
evals/
├── cases.jsonl              # 空白固定用例集
└── run.py                   # 评估入口占位，尚不能评估
runs/                        # 运行记录，内容默认不提交 Git
docs/                        # 学习和实验记录
.env.example
pyproject.toml
requirements.txt             # 保留：当前无第三方运行依赖
Makefile
README.md
```

`clients/business_api.py` 已实现 business-demo API v1 的类型化 HTTP 客户端：请求和响应使用泛型包装，各端点使用独立的 TypedDict 契约，并由客户端管理会话 Cookie、CSRF token、幂等键和超时。其他待实现的 Python 模块仍只含职责说明；空白提示文件不会被入口加载。执行 `evals/run.py` 会明确提示未实现并退出，不会产生虚假的通过结果。

## 目标运行结构（尚未实现）

```text
HTTP 入口 → 上下文与可信任务状态 → LLM
                                  ├── 回答或追问 → 返回用户
                                  └── 工具请求
                                        ↓
                             executor 校验 / 等待确认
                                        ↓
                                tools → 业务 HTTP API
                                        ↓
                              工具结果交回 LLM，继续循环
```

`runtime/limits.py` 在每轮和工具执行阶段限制次数及时间；`runtime/tracing.py` 记录运行过程。它们属于程序控制，不是可被模型跳过的工具。

不设置独立的“分类后进入固定业务分支”入口。未来需要确定性路由时，可在 `tools/routing.py` 定义能力，让模型按需调用；现在没有路由实现或工具注册。路由工具不能绕过执行控制或隐藏未经确认的写操作。业务权限与最终写入检查继续由 business-demo 后端保证。

原来的 `agent/runner.py` 已调整为 `runtime/loop.py`；`agent/context.py`、`agent/state.py` 移入 runtime；独立的 `agent/router.py` 移除。`models/`、`clients/`、`prompts/` 和 HTTP 启动方式保持原职责。

## 实践约定

每次只实现一个具体能力，先动手，遇到困难先寻求提示。使用固定输入比较改动，记录提示、模型、数据与程序问题。提示和代码先用 Git 管理；之后由运行记录关联版本、模型参数和实际结果，无需预先建立复杂发布平台。

业务工具必须调用 business-demo 的 HTTP API；身份权限、参数校验和可靠写入由程序保证。不要直接读取业务数据库，不在这里提前搭建 RAG、长期记忆或多 Agent。不保存真实密钥或未经脱敏的个人数据。
