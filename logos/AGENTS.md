# AGENTS.md — Logos Project Guide for AI Agents

## Project Overview

**Logos** is an LLM Engineering Platform that acts as an intelligent proxy between LLM consumers and multiple LLM providers (Azure, Ollama, OpenAI, and a fleet of self-hosted GPU workers running vLLM/Ollama). It provides usage logging, billing, central resource management, policy-based model selection, scheduling, GPU capacity planning, and monitoring.

This section (and most of this file) covers `logos-orchestrator/`, the Python/FastAPI service. See **Repository Structure** below for the other three services in this directory.

## Tech Stack (logos-orchestrator)

- **Language**: Python 3.13
- **Framework**: FastAPI (0.115.9) + Uvicorn
- **Database**: PostgreSQL 17 via SQLAlchemy 2.x (raw SQL with `text()`, NOT the ORM query API) — schema owned by `logos-webservice` (Liquibase), not by this service
- **HTTP Client**: httpx (async)
- **Dependency Management**: `uv` (lockfile: `logos-orchestrator/uv.lock`, committed). `pyproject.toml` still declares a Poetry-format `[tool.poetry]` packaging section, but there is no `poetry.lock` and installs go through `uv pip install .` / `uv sync`, not `poetry install`.
- **Testing**: pytest + pytest-asyncio (asyncio_mode = "auto")
- **Containerization**: Docker multi-stage build with `uv` (pinned), Docker Compose + Traefik v3
- **CI**: GitHub Actions (`.github/workflows/logos_test.yml`) — installs via `uv`, runs orchestrator unit tests, then a separate `logos-workernode` test step in the same job

## Repository Structure

`logos/` is a multi-service directory, not a single Python project. The
FastAPI service described in most of this file lives under
`logos-orchestrator/`, alongside three sibling services:

```
logos/
├── AGENTS.md                          # This file
├── docker-compose.yaml                # Full stack (db, orchestrator, webservice, ui, traefik)
├── docker-compose.dev.yaml            # Local dev variant with local builds
├── db/
│   └── Dockerfile                     # Plain postgres:17 + pg_cron — no schema baked in
├── logos-orchestrator/                # Python/FastAPI — proxy, scheduling, DB access
│   ├── pyproject.toml                 # Project + dependencies (Poetry-format metadata)
│   ├── uv.lock                        # Dependency lockfile (committed) — installed via uv, not poetry
│   ├── Dockerfile
│   ├── run_tests.sh                   # Test runner (unit|integration|sdi|performance|all)
│   ├── config/                        # Provider YAML configs
│   │   ├── config-azure.yaml
│   │   ├── config-openai.yaml
│   │   └── config-openwebui.yaml
│   ├── src/logos/
│   │   ├── main.py                    # FastAPI app + ALL route definitions (~6250 lines)
│   │   ├── auth.py                    # Authentication & authorization
│   │   ├── role_auth.py               # Role-based authorization checks
│   │   ├── responses.py               # Helper utilities (URL merging, token extraction)
│   │   ├── request_content.py         # Request payload parsing helpers
│   │   ├── model_string_parser.py     # logos-v* model string parser
│   │   ├── context_budget.py          # Estimates a request's context-window need for routing
│   │   ├── logosnode_registry.py      # Bridge/registry for connected logos-workernode fleet
│   │   ├── rate_limiter.py            # Per-process rate limiting
│   │   ├── timeouts.py                # Shared timeout constants
│   │   ├── terminal_logging.py        # Structured terminal/log output helpers
│   │   ├── errors.py                  # Shared error/exception types
│   │   ├── capacity/                  # GPU capacity planning (works with logos-workernode)
│   │   │   ├── capacity_planner.py
│   │   │   ├── calibration_orchestrator.py
│   │   │   ├── demand_tracker.py
│   │   │   ├── host_ram_ledger.py
│   │   │   ├── lane_comparator.py
│   │   │   └── vram_ledger.py
│   │   ├── dbutils/
│   │   │   ├── dbmanager.py           # All DB operations (~2750 lines) — context manager pattern
│   │   │   ├── dbmodules.py           # SQLAlchemy ORM models
│   │   │   └── dbrequest.py           # Pydantic request models
│   │   ├── pipeline/
│   │   │   ├── pipeline.py            # Classification → Scheduling → Execution orchestrator
│   │   │   ├── fcfs_scheduler.py      # FCFS scheduler with priority queue
│   │   │   ├── executor.py            # HTTP client for provider API calls
│   │   │   └── context_resolver.py    # DB lookups for auth/routing info
│   │   ├── classification/
│   │   │   └── classification_manager.py  # Multi-stage model classification
│   │   ├── queue/
│   │   │   └── priority_queue.py      # Thread-safe priority queue
│   │   ├── sdi/                       # Scheduling Data Interface
│   │   │   ├── ollama_facade.py
│   │   │   └── azure_facade.py
│   │   ├── monitoring/
│   │   │   ├── recorder.py            # Request event monitoring
│   │   │   └── ollama_monitor.py      # Background VRAM/model polling
│   │   └── jobs/
│   │       └── job_service.py         # Async job persistence
│   └── tests/
│       ├── conftest.py                # Global test config (stubs heavy deps)
│       ├── unit/                      # main/, sdi/, queue/, responses/, capacity/, ...
│       ├── integration/               # Full endpoint tests with mock providers
│       └── scheduling_data/           # SDI-specific tests
├── logos-workernode/                  # Python — GPU worker-node control plane; see its own AGENTS.md
│   └── logos_worker_node/             # lane_manager.py, calibration.py, logos_bridge.py, vllm_process.py, ...
├── logos-webservice/                  # Spring Boot (Java 25) — admin/stats API, owns the DB schema
│   └── src/main/resources/liquibase/  # Liquibase changelogs (000_initial_schema.xml onward) — the
│                                       # actual schema source of truth; NOT db/init.sql (see below)
└── logos-ui/                          # Angular frontend
```

**Sibling services, briefly**: `logos-workernode` runs on GPU hosts, connects
out to the orchestrator over a websocket bridge (`logosnode_registry.py` on
the orchestrator side), and handles vLLM/Ollama lane lifecycle, calibration,
and the HF compatibility precheck (see `logos-workernode/AGENTS.md`).
`logos-webservice` is a separate Spring Boot service that now owns the
Postgres schema (via Liquibase) and serves admin/statistics endpoints
independent of the FastAPI orchestrator. `logos-ui` is the Angular frontend
consuming both. The orchestrator's `DBManager` reads/writes the same
database but does not migrate it — see Database Schema below.

## Architecture & Key Patterns

### Monolithic main.py
All FastAPI routes are defined directly in `logos-orchestrator/src/logos/main.py`. There are NO separate router files. When adding new endpoints, add them to `main.py` or create a new router file and include it.

**Important**: The `/v1/{path:path}` catch-all route captures all `/v1/*` requests. Any new `/v1/...` routes (e.g., `/v1/models`) MUST be defined BEFORE the catch-all in the file, otherwise FastAPI will never match them.

### Database Pattern
- `DBManager` is a context manager: `with DBManager() as db: ...`
- All queries use raw SQL via `sqlalchemy.text()` — NOT ORM queries
- Connection string is hardcoded: `postgresql://postgres:root@logos-db:5432/logosdb`
- For tests, DBManager is typically mocked/monkeypatched
- DB methods return `(result_dict, status_code)` tuples — **always unpack** these and return proper `JSONResponse` objects from endpoints, never return raw tuples
- The orchestrator only reads/writes this database — it does not own the schema. See Database Schema below.

### Authentication
Single entry point in `auth.py`:
- **`authenticate_api_key(headers)`** → `AuthContext` (dataclass: `key_value`, `api_key_id`, `api_key_name`, `key_type`, `team_id`, `user_id`, `environment`, `log_level`, `settings`, `default_priority`, `cloud_rl`, `local_rl`). Looks the key up via `db.get_api_key_by_value`; raises 401 if missing/inactive.

Role-based authorization lives in `role_auth.py`, checked separately from the above (on `users.role`, not on the API key):
- **`require_logos_admin(request)`** — role must be `logos_admin`
- **`require_app_admin_or_above(request)`** — role must be `app_admin` or `logos_admin`
- **`require_logos_admin_or_team_owner(team_id, request, db)`** — `logos_admin`, or `app_admin` who owns *that* team (`team_members.is_owner`)

API keys are passed via: `logos_key` header, `logos-key` header, or `Authorization: Bearer <key>`

### Entity Hierarchy
```
User (role: app_developer | app_admin | logos_admin)
  └── Team(s), via team_members (is_owner flag)
        └── API Key(s) (key_type: developer | application)
              └── Model/Provider access, resolved per key:
                    use_custom_permissions=true  → that key's own
                      api_key_model_permissions / api_key_provider_permissions
                    use_custom_permissions=false → its team's
                      team_model_permissions / team_provider_permissions (default)
```
This replaced an older Process/Profile hierarchy (`process`, `profiles`,
`profile_model_permissions`, `model_api_keys` tables) — those tables no
longer exist; don't design against them.

### Request Flow
```
Request → Auth → Log
  ├── PROXY MODE (body has "model"): → Verify access → Resolve auth/URL → Execute
  └── RESOURCE MODE (no "model"):    → Classify → Schedule → Resolve → Execute
→ Log Response (tokens, provider, classifications, scheduling stats)
```

## Database Schema (Key Tables)

**Schema ownership**: the schema is defined and migrated by `logos-webservice`
(Spring Boot) via Liquibase changelogs
(`logos-webservice/src/main/resources/liquibase/changelog/`, currently
`000_initial_schema.xml` through `016_...xml`). There is no `db/init.sql`
and no `db/migrations/` in this repo anymore — `logos/db/` only holds the
plain `postgres:17` Dockerfile. The orchestrator's `dbmanager.py` reads and
writes these same tables but has no migration tooling of its own (still no
ORM/Alembic on the orchestrator side — raw SQL against a Liquibase-owned
schema).

| Table | Purpose |
|-------|---------|
| `users` | User accounts; `role` ∈ `app_developer`/`app_admin`/`logos_admin` |
| `teams` | Teams, with default rate-limit/budget columns |
| `team_members` | User ↔ team membership, with an `is_owner` flag |
| `api_keys` | API keys — `key_value` (unique), `key_type` (`developer`/`application`), owning `team_id`/`user_id`, `settings` (JSONB), `use_custom_permissions` |
| `team_model_permissions` / `team_provider_permissions` | Default access, inherited by keys with `use_custom_permissions=false` |
| `api_key_model_permissions` / `api_key_provider_permissions` | Per-key overrides, used when `use_custom_permissions=true` |
| `providers` | LLM providers (base_url, provider_type, auth config, SDI fields) |
| `models` | LLM models (name, endpoint, classification weights, tags) |
| `model_provider` | Model ↔ Provider mapping |
| `model_profiles` | Per-provider VRAM/calibration profile for a model (base residency, loaded/sleeping VRAM) — written by `logos-workernode` calibration |
| `logosnode_provider_keys` | Auth keys for the workernode websocket bridge, per provider |
| `ollama_provider_snapshots` | Periodic VRAM/loaded-model snapshots from Ollama providers |
| `policies` | Classification policies with threshold weights |
| `log_entry` | Request usage logs (timestamps, payloads, tokens, SDI metrics) |
| `usage_tokens` | Per-request token counts linked to log_entry |
| `token_types` | Token type definitions (prompt_tokens, completion_tokens, etc.) |
| `token_prices` | Billing prices (per-1000-token with valid_from dates) |
| `jobs` | Async job tracking, linked to the owning `api_key_id`/`team_id` |

The `api_keys.settings` JSONB field can store per-key configuration (e.g., rate limits).

## Adding New Features — Checklist

### Adding a new API endpoint
1. Add the route handler to `logos-orchestrator/src/logos/main.py` (or create a new router and include it)
2. Add any new Pydantic request models to `logos-orchestrator/src/logos/dbutils/dbrequest.py`
3. Add DB operations to `logos-orchestrator/src/logos/dbutils/dbmanager.py`
4. Write unit tests in `logos-orchestrator/tests/unit/`
5. If this needs a schema change, that's a `logos-webservice` change — see below. `dbmanager.py`/`dbmodules.py` must then be updated to match whatever Liquibase produces.

### Adding a database migration
Schema changes go through **`logos-webservice`** (Spring Boot), not this
service:
1. Create `logos-webservice/src/main/resources/liquibase/changelog/NNN_description.xml` (next number after the highest currently included — currently `016`)
2. **CRITICAL**: Add `<include file="liquibase/changelog/NNN_description.xml"/>` to `master.xml` in the same directory — Liquibase only applies changelogs listed there; a file left out is silently never run
3. Liquibase runs automatically on `logos-webservice` startup (`spring.liquibase.change-log` in `application.properties`) — no separate "apply migrations" step or fresh-install `init.sql` to keep in sync; there is none anymore
4. Back on the orchestrator side: update `dbmanager.py` (raw SQL) and `dbmodules.py` (ORM models) to match the new columns/tables

### Testing
```bash
# From logos-orchestrator/
uv venv .venv && source .venv/bin/activate
uv pip install .
uv pip install "coverage[toml]" pytest-timeout   # matches CI

# Run unit tests only
./run_tests.sh unit

# Run the full suite directly
pytest tests/unit -v

# Run specific test file
pytest tests/unit/main/test_route_and_execute.py -v
```

Tests stub heavy dependencies (sentence_transformers, gRPC) via `conftest.py`. DBManager should be monkeypatched in tests — never connect to a real database in unit tests.

**Note**: `pytest tests/unit` currently passes ~1060 tests (1 xfailed) on `main` — treat any exact count here as a snapshot, not a target; re-run rather than trust a stale number. Tests use `asyncio_mode = "auto"` so `@pytest.mark.asyncio` decorators are NOT needed on test functions. CI (`.github/workflows/logos_test.yml`) runs this suite plus a separate `logos-workernode` test step in the same job — a change touching both services needs both green.

## Git Workflow & Pull Requests

### Naming Conventions (MANDATORY)

**PR Title** — Must match this regex (enforced by CI):
```
^`(Development|General|Athena|Atlas|AtlasML|Iris|Logos|Memiris)`:\s[A-Z].*$
```
Examples:
- `` `Logos`: Add OpenAI-compatible /v1/models endpoint ``
- `` `Logos`: Fix rate limiting for batch users ``

**Commit Messages** — Must follow the same pattern (without backticks):
```
ProjectName: Description starting with capital letter (#issue_number)
```
Examples:
- `Logos: Add OpenAI-compatible /v1/models endpoint (#420)`
- `Logos: Fix rate limiting for batch users (#422)`

**Branch Names**: `feature/logos/description` or `logos/description`

### ALWAYS Create Pull Requests for Issues
When implementing a feature for a GitHub issue:
1. Create a feature branch from `main`: `git checkout -b feature/logos/short-description`
2. Implement the feature with tests
3. Run ALL existing tests to verify zero regressions: `pytest tests/unit/ -v` (from `logos-orchestrator/`, in its `uv` venv — see Testing above)
4. Commit with proper message format: `Logos: Description (#issue_number)`
5. Push the branch: `git push origin feature/logos/short-description`
6. **Create a PR** with `gh pr create`:
   - Title MUST match the PR title regex above (with backtick-wrapped project name)
   - Body should include: `Closes #NNN`, summary, changes list, new endpoints, testing info
7. **After PR creation, ALWAYS**:
   - Check CI/build status within a few minutes: `gh pr checks <PR_NUMBER>`
   - If the PR title validation fails, fix it immediately with `gh pr edit <NUMBER> --title '...'`
   - If tests fail, fix them before requesting review
   - Monitor until all checks pass
8. Never merge directly to `main` without a PR

### PR Description Template
```markdown
## Closes #NNN

## Summary
Brief description of what this PR implements.

## Changes
- `file1.py`: Description of change
- `file2.py`: Description of change

## New Endpoints
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/v1/models` | API Key | List accessible models |

## Testing
- Added N tests in `tests/unit/...`
- Run: `pytest tests/unit/ -v`

## Database Changes
- Migration: `logos-webservice/.../liquibase/changelog/NNN_description.xml` (if any)
```

### Post-PR Checklist
After creating a PR, always verify:
1. **Title validation passes** — check with `gh pr checks <NUMBER>` or view on GitHub
2. **All CI checks pass** — build, lint, tests
3. **No merge conflicts** — rebase on main if needed
4. If any check fails, fix immediately — do NOT leave failing PRs

## Conventions

- **Imports**: Use absolute imports from `logos.*` (e.g., `from logos.auth import authenticate_api_key`)
- **Async**: All route handlers are `async def`; use `await` for DB and HTTP operations
- **Error handling**: Raise `HTTPException` with appropriate status codes
- **Response format**: Admin endpoints should return `JSONResponse(content=result, status_code=status)` — never return raw tuples from endpoints
- **Naming**: Snake_case for functions/variables, PascalCase for classes
- **Type hints**: Use them consistently (typing module + dataclasses)
- **SQL**: Use parameterized queries with `:param_name` syntax in `text()` calls
- **Docstrings**: All public functions should have docstrings explaining params, returns, raises

## Environment & Running

```bash
# Install dependencies
cd logos/logos-orchestrator && uv venv .venv && source .venv/bin/activate && uv pip install .

# Run locally
uvicorn logos.main:app --host 0.0.0.0 --port 8000

# Run the full stack with Docker (from logos/)
docker compose up --build

# Database is at logos-db:5432/logosdb (user: postgres, pass: root)
```

## Operations Runbook

### Creating Logos API Keys for a New Consumer

**Outdated — do not follow the steps that used to be here.** They called
`/logosdb/add_service`, `/logosdb/connect_service_process`,
`/logosdb/add_profile`, `/logosdb/connect_profile_model` and read/wrote the
`process`/`services`/`profiles`/`profile_model_permissions` tables — none
of that exists anymore (see Entity Hierarchy above: it's now
Users → Teams → API Keys).

Team and API-key administration now lives entirely in **`logos-webservice`**
(Spring Boot), not `logos-orchestrator` — see
`TeamController.java`, `ApiKeyAdminController.java`, and `MeController.java`
under
`logos-webservice/src/main/java/.../identity/controller/`. Auth for that
service appears to be Keycloak-based (see the
`001_keycloak_identity.xml` Liquibase changelog), not the old root-`logos_key`
curl pattern. **Not yet re-verified in detail** — read those controllers (and
`logos-ui`'s corresponding admin screens, if a UI flow is preferred) before
running any of this against production, and replace this note with a
verified step-by-step once done.

### Testing an API Key with curl

The external URL is `https://logos.aet.cit.tum.de:8080`. Traefik handles TLS on port 8080.

```bash
curl -X POST https://logos.aet.cit.tum.de:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <LOGOS_KEY>" \
  -d '{
    "model": "<model-name>",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

**Important**: Use `/v1/...` path (not `/openai/v1/...`). The `/openai/` prefix is a separate proxy route, not a path prefix for the OpenAI-compatible API.

### Useful DB Queries

**Outdated — the queries that used to be here joined `process`/`services`/
`profiles`/`profile_model_permissions`, none of which exist anymore.** The
current equivalents would join `api_keys`/`teams`/`team_members`/
`team_model_permissions` (see Database Schema above) — not yet rewritten
and verified against production; do that before relying on it.

```bash
# List all available models — this one is still accurate, unaffected by
# the entity-model change:
ssh logos "docker exec logos-db psql -U postgres -d logosdb -c \"SELECT id, name FROM models ORDER BY name;\""
```

## Important Notes for AI Agents

1. **main.py is large** (~6250 lines). Read specific sections rather than the whole file. Use grep to find relevant routes/functions.
2. **DBManager is the critical class** for all database operations. It auto-commits on exit.
3. **No Alembic/migration tooling on the orchestrator side** — it never had any; it just reads/writes tables. Schema and migrations are owned by `logos-webservice` via Liquibase (see Database Schema above).
4. **Provider types**: `cloud` (Azure/OpenAI), `ollama` (local Ollama instances), and self-hosted GPU workers via `logos-workernode` (vLLM/Ollama lanes, connected over the websocket bridge in `logosnode_registry.py`).
5. **Token tracking exists** in the `usage_tokens` and `token_prices` tables.
6. **`api_keys` is the key auth entity** — each key has a unique `key_value`, and belongs to a `team_id` and/or `user_id`. There is no `process` table anymore.
7. **Model/provider access is team-scoped by default** — `team_model_permissions`/`team_provider_permissions`, unless a key sets `use_custom_permissions=true` and gets its own `api_key_model_permissions`/`api_key_provider_permissions` rows. There is no `profiles` table anymore.
8. **Existing tests mock DBManager** — follow the same pattern for new tests.
9. **When adding OpenAI-compatible endpoints** (like `/v1/models`), follow the OpenAI API spec exactly.
10. **For schema changes**: add a Liquibase changelog in `logos-webservice` and include it in `master.xml` (see Adding a database migration above), then update `dbmanager.py`/`dbmodules.py` here to match.
11. **DB method return values**: Methods returning `(dict, int)` tuples must be unpacked in endpoints — use `JSONResponse(content=result, status_code=status)`, never return the tuple directly.
12. **Route ordering matters**: FastAPI matches routes in definition order. Specific routes must come before catch-all routes like `/v1/{path:path}`.
13. **Docker build**: Uses multi-stage build with `uv` (pinned version) for fast dependency installation. Runtime stage uses slim Python image with `VIRTUAL_ENV=/opt/venv`.
14. **`api_keys.settings` JSONB**: Flexible per-key config store. Used for rate limits and other settings. No schema migration needed to add new keys.
15. **Traefik routing**: The domain is configured via the `LOGOS_DOMAIN` environment variable (default: `localhost`); Let's Encrypt ACME registration uses `ACME_EMAIL`. All surfaces (web UI, Swagger `/docs`, completion API, Spring `/api` backend — i.e. `logos-webservice`) are served together on the default HTTPS port, routed by path and router priority. See `.env.example` for production setup.
16. **Shared dependency**: The `shared/` sibling directory is symlinked into the orchestrator for local dev/CI: `ln -s ../../shared logos/logos-orchestrator/shared` (note the extra `../` — `shared/` is a sibling of `logos/`, and the orchestrator now lives one level deeper than it used to).
17. **Not yet re-verified since the Liquibase move**: whether `dbmodules.py` (ORM) still drifts from the real schema the way it used to against the old `init.sql`. Re-check before relying on this claim either way.
18. **CI caching**: The CI workflow installs dependencies via `uv` (`astral-sh/setup-uv`), not Poetry — there is no Poetry cache step anymore.
