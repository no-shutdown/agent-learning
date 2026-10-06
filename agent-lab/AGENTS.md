# Learner-owned Agent project

This project deliberately starts empty. The user is learning by implementing it themselves.

- Current scope: application configuration, model and business HTTP clients, business tools and their tests, documentation, remaining empty learning modules and the HTTP entry in `src/agent_lab/main.py`. `src/main.py` remains a compatibility launcher. Tools were implemented at the user’s explicit request; the model adapter is implemented; the loop supports native tool_calls with an injected executor; ToolExecutor is implemented; HTTP integration, website confirmation UI and in-memory conversation continuation are implemented. Structured local tracing is implemented at the user’s request; log model payloads and tool results with credential redaction, without hidden reasoning.
- Do not proactively implement prompts, intent routing, model adapters, business HTTP tools, execution loops, RAG, persistent memory or multiple Agents.
- Teach one concrete capability at a time with objective, input, expected output and acceptance criteria. Let the user attempt it first; offer hints before small code examples. Implement a whole Agent only when explicitly requested.
- Business operations must go through business-demo's HTTP API. Authentication, validation and reliable writes remain enforced by that website.
- Use fixed cases to compare prompt versions. Separate prompt, model, data and program failures. Keep experiment records lightweight.
- `make run` starts the Agent HTTP service on 127.0.0.1:8001; `make check` runs the scoped mypy type check plus syntax checks in src, evals and tests; `make test` runs tool-layer tests. Runtime uses only Python's standard library.
- Never write real credentials in source, documentation or version control.
- Do not alter the user's Desktop learning notes unless explicitly requested.

## Architecture direction

- Use an LLM-led tool-calling loop in `runtime/loop.py`; do not introduce a mandatory intent-classification router before it.
- Future deterministic routing may be exposed as an optional tool in `tools/routing.py`. Keep it unimplemented until an exercise requests it.
- All tool requests must pass through the runtime executor. Confirmation, authority, limits and timeouts are mandatory program controls, not optional model-selected tools.
- Keep remaining placeholder modules empty unless explicitly requested. `tools/registry.py` only collects tools, looks them up and returns descriptions. It must not handle sessions, authorization, confirmations or execution. These controls belong to runtime/executor.py, now implemented at the user’s request. `Tool.invoke` is a low-level client adapter, not a model-facing execution entry point.

- Application environment variables are read only by `config.load_settings()`. Clients accept explicit constructor parameters and retain their own validation/defaults; they must not depend on application globals. Use `BUSINESS_API_BASE_URL`. Keep data contracts in their owning submodules; do not recreate a catch-all top-level schemas module.

- Use native model tool calling only: descriptions go through the model API tools field, user/assistant/tool history uses native message roles. Do not reintroduce prompt tool-list placeholders or interpret assistant content JSON as executable tool requests.

- The loop depends only on models/contracts.py (ChatModel.generate, ModelRequest, ModelResponse, Message, ToolCall). Provider-specific message serialization, native response parsing, missing call-ID generation and error adaptation belong in each model client. Keep confirmation/cancellation history in the same neutral Message type. Only main selects concrete adapters.

- Keep HTTP/application boundaries explicitly typed: AgentHTTPServer owns application at construction, Handler.server is typed, and Conversation fields must not regress to object or untyped containers. Run make check and make test for relevant changes. Mypy coverage is intentionally gradual and listed in pyproject.toml; do not blanket-ignore new boundary errors.
