# Learner-owned Agent project

This project deliberately starts empty. The user is learning by implementing it themselves.

- Current scope: configuration, documentation, empty learning modules and the HTTP placeholder in `src/agent_lab/main.py`. `src/main.py` remains a compatibility launcher.
- Do not proactively implement prompts, intent routing, model adapters, business HTTP tools, execution loops, RAG, persistent memory or multiple Agents.
- Teach one concrete capability at a time with objective, input, expected output and acceptance criteria. Let the user attempt it first; offer hints before small code examples. Implement a whole Agent only when explicitly requested.
- Business operations must go through business-demo's HTTP API. Authentication, validation and reliable writes remain enforced by that website.
- Use fixed cases to compare prompt versions. Separate prompt, model, data and program failures. Keep experiment records lightweight.
- `make run` starts the placeholder on 127.0.0.1:8001; `make check` verifies syntax in src and evals. Runtime uses only Python's standard library.
- Never write real credentials in source, documentation or version control.
- Do not alter the user's Desktop learning notes unless explicitly requested.

## Architecture direction

- Use an LLM-led tool-calling loop in `runtime/loop.py`; do not introduce a mandatory intent-classification router before it.
- Future deterministic routing may be exposed as an optional tool in `tools/routing.py`. Keep it unimplemented until an exercise requests it.
- All tool requests must pass through the runtime executor. Confirmation, authority, limits and timeouts are mandatory program controls, not optional model-selected tools.
- Keep this scaffold empty: module responsibilities are documentation, not a request to implement the loop or tools.
