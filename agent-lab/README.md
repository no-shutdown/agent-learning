# Agent Lab：学习项目骨架

以 LLM 选择工具、程序受控执行、真实结果反馈的循环为主线。使用 Python 标准库保留可运行的 HTTP 空服务；业务 HTTP 客户端、工具层和 Ollama 模型适配器已实现，Agent 循环及工具执行器已实现，HTTP 接入和确认交互仍待练习。

## 启动

```sh
cd /Users/colin/code/my/agent-learning/agent-lab
make run
```

默认监听 `127.0.0.1:8001`。GET `/health` 返回服务状态；POST `/chat` 接受 `{"message":"你好"}`，校验输入后返回固定的“Agent 尚未实现”。网站 AI 助手面板和父目录的启动网站脚本保持兼容。

重建虚拟环境用 `make setup`；`make check` 检查 src、evals 和 tests 的语法；`make test` 运行配置和工具层测试。当前没有第三方运行依赖。`pyproject.toml` 提供项目、打包和 Ruff 配置，不要求现在安装框架或 SDK。

可复制 `.env.example` 为 `.env`；`make run` 与父目录启动器会加载它。`config.load_settings()` 统一读取并校验环境变量，启动入口用其中的 `AGENT_PORT` 启动占位服务；业务和模型配置供后续运行链显式注入客户端。直接运行 Python 时需自行注入环境变量，配置模块不自动加载 `.env`。Ollama 由 App 独立启动，默认 API 地址为 `http://127.0.0.1:11434`。

## 配置与数据契约

统一配置键：`AGENT_PORT`、`BUSINESS_API_BASE_URL`、`BUSINESS_API_TIMEOUT_SECONDS`、
`MODEL_BASE_URL`、`MODEL_NAME`、`MODEL_TIMEOUT_SECONDS`，默认值见 `.env.example`。
地址、模型名不能为空；端口范围为 1～65535，超时必须为有限正数（秒）。
无效配置抛出 `ConfigError`，错误信息只含变量名，不回显配置值。

模块独立使用时采用构造参数和本地默认值；使用环境配置时显式注入：

```python
from agent_lab.config import load_settings
from agent_lab.clients import BusinessApiTransport
from agent_lab.models import OllamaClient

settings = load_settings()
transport = BusinessApiTransport(
    settings.business_api_base_url,
    timeout_seconds=settings.business_api_timeout_seconds,
)
model = OllamaClient(
    settings.model_base_url,
    settings.model_name,
    timeout_seconds=settings.model_timeout_seconds,
)
```

每个用户单独创建业务 transport，不保存共享登录会话。配置读取及客户端构造不发起网络请求。
旧变量名 `BUSINESS_BASE_URL` 已停用；改为 `BUSINESS_API_BASE_URL`。
本地 Ollama 客户端未实现 API Key 认证，示例不再保留未使用的 `MODEL_API_KEY`。

顶层空白 `schemas.py` 已移除。业务请求/响应、模型协议、工具契约仍分别归属
`clients/`、`models/`、`tools/`。Agent 运行协议待实现时放在 `runtime/`，
不提前创建通用协议集合；`TypedDict` 类型声明不等于运行时校验。

## 模型接入方式

由 Ollama App 在本机运行模型并提供 HTTP API。`OllamaClient` 使用标准库调用 `/api/chat`，默认地址为 `http://127.0.0.1:11434`、模型为 `qwen3.5:9b`，应用配置读取 `MODEL_BASE_URL` 和 `MODEL_NAME` 后显式传给客户端；客户端本身不再读取环境变量。通过 `from agent_lab.models import OllamaClient` 导入；`chat(messages, tools=...)` 返回完整模型响应，工具调用由注入的运行时执行器负责，`ToolExecutor` 已实现，使用方法见 [执行器说明](docs/executor.md)。原生协议与 Ollama 内部机制见 [工具调用说明](docs/native-tool-calling.md)。

旧的独立 `model-service` 管理项目已删除。Agent 不依赖该项目、Open WebUI 或 Docker；业务操作仍通过 business-demo 的 HTTP API 执行。

## 目录

```text
src/
├── main.py                   # 兼容旧启动命令，转发到包入口
└── agent_lab/
    ├── __init__.py
    ├── main.py               # 已有的最小 HTTP 服务
    ├── config.py             # 应用配置读取与校验（已实现）
    ├── runtime/
    │   ├── loop.py           # 原生 tool_calls 循环，需注入执行器
    │   ├── context.py        # 本轮消息、提示与工具上下文（待实现）
    │   ├── state.py          # 任务及待确认操作状态（待实现）
    │   ├── executor.py       # 工具校验、确认、去重、执行及结果转换
    │   ├── contracts.py      # 工具请求、执行结果及协议校验
    │   ├── limits.py         # 调用预算、超时和停止条件（待实现）
    │   └── tracing.py        # 运行与工具调用记录（待实现）
    ├── models/
    │   └── ollama.py         # Ollama 聊天 API 客户端
    ├── tools/
    │   ├── registry.py       # 工具目录、按 ID 查找与描述（已实现）
    │   ├── orders.py         # 订单查询与操作工具（已实现）
    │   ├── addresses.py      # 地址簿工具（已实现）
    │   ├── products.py       # 商品与管理员维护工具（已实现）
    │   ├── operations.py     # 操作结果核实工具（已实现）
    │   ├── contracts.py      # 工具契约和参数校验（已实现）
    │   └── routing.py        # 未来可选的分类或分派工具（未注册）
    ├── clients/
    │   ├── __init__.py       # 统一导出模块客户端与契约
    │   ├── orders_api.py     # 订单 HTTP 客户端（其他模块同理）
    │   ├── transport.py      # 每用户 HTTP 会话、Cookie、CSRF 与超时
    │   └── pojo/             # 通用请求和响应类型
    └── prompts/
        ├── agent.md          # 系统规则，通过 messages 传入模型
        └── loader.py         # 系统提示加载与文本版本（已实现）
tests/                       # 配置、工具、执行器及循环接入测试
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

`clients/` 按业务模块提供 business-demo API v1 的类型化 HTTP 客户端，由包的 `__init__.py` 统一导出：请求和响应使用泛型包装，各端点使用独立的 TypedDict 契约，并由客户端管理会话 Cookie、CSRF token、幂等键和超时。工具层提供 18 个业务动作；注册表只管理工具目录，执行控制由 runtime/executor.py 实现。使用方法与职责边界见 [工具说明](docs/tools.md)。其余待实现模块仍只含职责说明；HTTP 入口尚未连接模型循环；循环本身已加载系统提示。执行 `evals/run.py` 会明确提示未实现并退出，不会产生虚假的通过结果。

## 目标运行结构（尚未全部接通）

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

不设置独立的“分类后进入固定业务分支”入口。未来需要确定性路由时，可在 `tools/routing.py` 定义能力，让模型按需调用；现在没有路由实现或路由工具注册。路由工具不能绕过执行控制或隐藏未经确认的写操作。业务权限与最终写入检查继续由 business-demo 后端保证。

原来的 `agent/runner.py` 已调整为 `runtime/loop.py`；`agent/context.py`、`agent/state.py` 移入 runtime；独立的 `agent/router.py` 移除。`models/`、`clients/`、`prompts/` 和 HTTP 启动方式保持原职责。

## 实践约定

每次只实现一个具体能力，先动手，遇到困难先寻求提示。使用固定输入比较改动，记录提示、模型、数据与程序问题。提示和代码先用 Git 管理；之后由运行记录关联版本、模型参数和实际结果，无需预先建立复杂发布平台。

业务工具必须调用 business-demo 的 HTTP API；身份权限、参数校验和可靠写入由程序保证。不要直接读取业务数据库，不在这里提前搭建 RAG、长期记忆或多 Agent。不保存真实密钥或未经脱敏的个人数据。
