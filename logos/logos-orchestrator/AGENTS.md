# AGENTS.md — logos-orchestrator

Python 3.13 / FastAPI / Uvicorn service: the LLM proxy core — authentication, classification, scheduling, provider routing, request logging.

- **Dependencies**: `uv` (lockfile `uv.lock`, committed). `pyproject.toml` still declares a Poetry-format `[tool.poetry]` section, but there is no `poetry.lock` — installs go through `uv pip install .` / `uv sync`.
- **DB**: PostgreSQL 17 via SQLAlchemy 2.x raw SQL (`text()`, NOT the ORM query API). Schema owned by `logos-webservice` (Liquibase) — this service has no migration tooling.
- **Testing**: pytest + pytest-asyncio (`asyncio_mode = "auto"`).
- **CI**: `.github/workflows/logos_test.yml` — orchestrator unit tests plus a `logos-workernode` test step in the same job; a change touching both needs both green.

## Where new code goes

`src/logos/main.py` owns the FastAPI `app`, exception handlers, middleware, and shared runtime helpers (pipeline startup, request execution). All route handlers live in `src/logos/routers/`, included at the bottom of `main.py`:

- `monitoring.py` — `/health`, `/metrics`
- `internal.py` — secret-gated `/internal/*` (Spring webservice)
- `logosnode.py` — worker provider endpoints `/logosdb/providers/logosnode/*`
- `admin.py` — `/logosdb/scheduler_state` (gated on `LOGOS_INTERNAL_SECRET`)
- `user_facing.py` — public OpenAI-compatible API: models, audio, `/v1/{path:path}` catch-all, jobs — included **last**

Rules:

- **New endpoints** go in the matching router module — never into `main.py`.
- **New helpers** go in a domain module (`live_stream.py`, `middleware.py`, ...) — never into `main.py`, unless several routers genuinely share them.
- A module approaching ~1000 lines is a signal to split it (soft guideline; `capacity/capacity_planner.py` currently violates it).
- **Route ordering matters**: the `/v1/{path:path}` catch-all in `user_facing.py` swallows all `/v1/*`. New `/v1/...` routes must be defined above it, and new routers must be `include_router`-ed in `main.py` before `user_facing`.
- **Shared state**: routers import from `logos.main`, which works only because `main.py` imports routers at its very bottom. Globals that startup rebinds (`_pipeline`, `_queue_mgr`, `_logosnode_facade`, ...) must be read via `import logos.main as _main` + `_main.<name>` — a plain `from logos.main import <name>` freezes the pre-startup `None`.
- Endpoint request models live in `dbutils/dbrequest.py`.

`main.py` is still ~4000 lines — read sections and grep, don't read it whole.

## Database pattern

- `DBManager` (`dbutils/dbmanager.py`) is a context manager: `with DBManager() as db: ...`. Auto-commits on exit.
- All queries use parameterized raw SQL via `sqlalchemy.text()` with `:param_name` syntax.
- DB methods return `(result_dict, status_code)` tuples — **always unpack** and return `JSONResponse(content=result, status_code=status)` from endpoints, never raw tuples.
- For tests, `DBManager` is mocked/monkeypatched — never connect to a real DB in unit tests.

## Authentication

Single entry point `auth.py: authenticate_api_key(headers)` → `AuthContext` dataclass; looks the key up via `db.get_api_key_by_value` (joins `users` for the caller role, `teams` for queue priority), 401 if missing/inactive. Keys arrive via `logos_key` header, `logos-key` header, or `Authorization:`.

Role-based authorization is separate (`role_auth.py`, on `users.role`):

- `require_logos_admin(request)`
- `require_app_admin_or_above(request)`
- `require_logos_admin_or_team_owner(team_id, request, db)`

## Request flow

```text
Request → Auth → Log
  ├── PROXY MODE (body has "model"): → Verify access → Resolve auth/URL → Execute
  └── RESOURCE MODE (no "model"):    → Classify → Schedule → Resolve → Execute
→ Log Response (tokens, provider, classifications, scheduling stats)
```

`log_entry` rows are inserted at request arrival and updated later with routing, lifecycle timestamps, status, usage, and settled cost.

## Adding a new API endpoint — checklist

1. Route handler in the matching module under `src/logos/routers/` (not `main.py`).
2. Pydantic request models in `src/logos/dbutils/dbrequest.py`.
3. DB operations in `src/logos/dbutils/dbmanager.py`.
4. Unit tests in `tests/unit/`.
5. Schema change needed? That's a `logos-webservice` change (see its `AGENTS.md`) — then update `dbmanager.py`/`dbmodules.py` here to match.

## Testing

```bash
cd logos-orchestrator
uv venv .venv && source .venv/bin/activate
uv pip install .
uv pip install "coverage[toml]" pytest-timeout   # matches CI

./run_tests.sh unit          # unit tests only
pytest tests/unit -v         # full suite
pytest tests/unit/main/test_route_and_execute.py -v   # one file
```

Tests stub heavy dependencies (sentence_transformers, gRPC) via `tests/conftest.py`. `asyncio_mode = "auto"` — no `@pytest.mark.asyncio` decorators needed. `run_tests.sh` also has `integration|sdi|performance|all` tiers.

## Conventions

- Absolute imports from `logos.*` (`from logos.auth import authenticate_api_key`).
- All route handlers are `async def`; `await` DB and HTTP operations.
- Raise `HTTPException` with appropriate status codes.
- Snake_case functions/variables, PascalCase classes, consistent type hints (typing + dataclasses).
- Docstrings on public functions (params, returns, raises).
- Provider types: `cloud` (Azure/OpenAI) and self-hosted GPU workers via `logos-workernode` (websocket bridge: `logosnode_registry.py`).
- `api_keys.settings` JSONB: flexible per-key config (e.g. rate limits) — no migration needed for new keys.
- Docker build: multi-stage with pinned `uv`; runtime uses slim Python with `VIRTUAL_ENV=/opt/venv`. **Python must stay 3.13** — 3.14 breaks tiktoken/PyO3 builds.
- The repo-root `shared/` directory is symlinked in for local dev/CI: `ln -s ../../shared logos/logos-orchestrator/shared`.

## Running

```bash
uvicorn logos.main:app --host 0.0.0.0 --port 8000        # local
docker compose -f ../docker-compose.dev.yaml up --build   # full stack (from logos/)
# Database at logos-db:5432/logosdb (user: postgres, pass: root)
```

## Testing a deployed API key with curl

Traefik handles TLS on port 8080 at `https://logos.aet.cit.tum.de:8080`:

```bash
curl -X POST https://logos.aet.cit.tum.de:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: <logos-api-key>" \
  -d '{"model": "<model-name>", "messages": [{"role": "user", "content": "Hello"}]}'
```

Use `/v1/...` paths — the `/openai/` prefix is a separate proxy route, not a path prefix for the OpenAI-compatible API.
