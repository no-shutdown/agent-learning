# Business baseline

This is the independent local business website for repeated Agent exercises. Keep business permissions, input validation, atomic state changes and idempotency in this project. Agent clients must use HTTP, never directly edit its database.

- Python application code: `src/`; HTML: `templates/`; static assets: `assets/`; tests: `tests/`; documentation: `docs/`.
- `make check` runs Ruff formatting/lint and Django checks. `make test` runs the backend suite in an isolated database.
- `make run` binds to 127.0.0.1:8000. Restart after Python/template changes.
- `make reset` destroys only the configured demo database's business data and regenerates fixtures. Never reset user experiments without their request or a clearly scoped verification workflow.
- Maintain API.md and SCENARIOS.md when changing contracts or fixed fixtures.
- Do not add prompts, routing, an Agent loop, RAG, memory or multi-agent logic to the business website.
- Preserve the user's Desktop learning documents; only edit them when explicitly asked.
- Do not commit `.env`, `.local-secret`, databases, sessions, logs or real credentials.
