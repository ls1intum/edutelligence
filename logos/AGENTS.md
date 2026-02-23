# AGENTS.md — Logos Project Guide for AI Agents

## Project Overview

**Logos** is an LLM Engineering Platform that acts as an intelligent proxy between LLM consumers and multiple LLM providers (Azure, Ollama, OpenAI). It provides usage logging, billing, central resource management, policy-based model selection, scheduling, and monitoring.

## Tech Stack

- **Language**: Python 3.13
- **Framework**: FastAPI (0.115.9) + Uvicorn
- **Database**: PostgreSQL 17 via SQLAlchemy 2.x (raw SQL with `text()`, NOT the ORM query API)
- **HTTP Client**: httpx (async)
- **Dependency Management**: Poetry 2.x (lockfile: `poetry.lock`)
- **Testing**: pytest + pytest-asyncio (asyncio_mode = "auto")
- **Containerization**: Docker multi-stage build with `uv` (pinned), Docker Compose + Traefik v3
- **CI**: GitHub Actions (`.github/workflows/logos_test.yml`) — runs unit tests with Poetry cache

## Repository Structure

```
logos/
├── AGENTS.md                          # This file
├── pyproject.toml                     # Poetry config + dependencies
├── poetry.lock                        # Dependency lockfile (committed)
├── .env.example                       # Environment variable template
├── Dockerfile                         # Multi-stage Docker build (uv for deps)
├── docker-compose.yaml                # Full stack (db, app, ui, landing, traefik)
├── docker-compose.dev.yaml            # Local dev variant with local builds
├── run_tests.sh                       # Test runner (unit|integration|sdi|performance|all)
├── config/                            # Provider YAML configs
│   ├── config-azure.yaml
│   ├── config-openai.yaml
│   └── config-openwebui.yaml
├── db/
│   ├── init.sql                       # Full DDL schema (source of truth)
│   └── migrations/                    # Sequential SQL migration scripts (###_name.sql)
│       ├── run_all_migrations.sh
│       └── README.md
├── src/logos/
│   ├── main.py                        # FastAPI app + ALL route definitions (~1690 lines)
│   ├── auth.py                        # Authentication & authorization
│   ├── responses.py                   # Helper utilities (URL merging, token extraction)
│   ├── model_string_parser.py         # logos-v* model string parser
│   ├── dbutils/
│   │   ├── dbmanager.py               # All DB operations (~2170 lines) — context manager pattern + ensure_schema()
│   │   ├── dbmodules.py               # SQLAlchemy ORM models
│   │   └── dbrequest.py               # Pydantic request models
│   ├── pipeline/
│   │   ├── pipeline.py                # Classification → Scheduling → Execution orchestrator
│   │   ├── fcfs_scheduler.py          # FCFS scheduler with priority queue
│   │   ├── executor.py                # HTTP client for provider API calls
│   │   └── context_resolver.py        # DB lookups for auth/routing info
│   ├── classification/
│   │   └── classification_manager.py  # Multi-stage model classification
│   ├── queue/
│   │   └── priority_queue.py          # Thread-safe priority queue
│   ├── sdi/                           # Scheduling Data Interface
│   │   ├── ollama_facade.py
│   │   └── azure_facade.py
│   ├── monitoring/
│   │   ├── recorder.py                # Request event monitoring
│   │   └── ollama_monitor.py          # Background VRAM/model polling
│   └── jobs/
│       └── job_service.py             # Async job persistence
└── tests/
    ├── conftest.py                    # Global test config (stubs heavy deps)
    ├── unit/
    │   ├── main/                      # Tests for main.py functions
    │   ├── sdi/                       # Tests for SDI facades
    │   ├── queue/                     # Tests for priority queue
    │   └── responses/                 # Tests for proxy behavior
    ├── integration/                   # Full endpoint tests with mock providers
    └── scheduling_data/               # SDI-specific tests
```

## Architecture & Key Patterns

### Monolithic main.py
All FastAPI routes are defined directly in `src/logos/main.py`. There are NO separate router files. When adding new endpoints, add them to `main.py` or create a new router file and include it.

**Important**: The `/v1/{path:path}` catch-all route captures all `/v1/*` requests. Any new `/v1/...` routes (e.g., `/v1/models`) MUST be defined BEFORE the catch-all in the file, otherwise FastAPI will never match them.

### Database Pattern
- `DBManager` is a context manager: `with DBManager() as db: ...`
- All queries use raw SQL via `sqlalchemy.text()` — NOT ORM queries
- Connection string is hardcoded: `postgresql://postgres:root@logos-db:5432/logosdb`
- For tests, DBManager is typically mocked/monkeypatched
- DB methods return `(result_dict, status_code)` tuples — **always unpack** these and return proper `JSONResponse` objects from endpoints, never return raw tuples

### Authentication
Three levels defined in `auth.py`:
1. **`authenticate_logos_key(headers)`** → `(logos_key, process_id)` — for admin endpoints
2. **`authenticate_with_profile(headers)`** → `AuthContext(logos_key, process_id, profile_id, profile_name)` — for model execution
3. **`check_authorization(logos_key)`** — verifies root user role for `/logosdb/` admin endpoints

API keys are passed via: `logos_key` header, `logos-key` header, or `Authorization: Bearer <key>`

### Entity Hierarchy
```
User → Process (has logos_key) → Profile(s) → Model Permissions → Models → Providers
```

### Request Flow
```
Request → Auth → Log
  ├── PROXY MODE (body has "model"): → Verify access → Resolve auth/URL → Execute
  └── RESOURCE MODE (no "model"):    → Classify → Schedule → Resolve → Execute
→ Log Response (tokens, provider, classifications, scheduling stats)
```

## Database Schema (Key Tables)

| Table | Purpose |
|-------|---------|
| `users` | User accounts (id, username, email, prename, name) |
| `services` | Service definitions |
| `process` | API key holders — `logos_key` (unique), links to user or service, log level, settings (JSONB) |
| `profiles` | Access profiles linked to a process |
| `providers` | LLM providers (base_url, provider_type, auth config, SDI fields) |
| `models` | LLM models (name, endpoint, classification weights, tags) |
| `model_provider` | Model ↔ Provider mapping |
| `model_api_keys` | API keys per model-provider pair |
| `profile_model_permissions` | Which profiles can access which models |
| `policies` | Classification policies with threshold weights |
| `log_entry` | Request usage logs (timestamps, payloads, tokens, SDI metrics) |
| `usage_tokens` | Per-request token counts linked to log_entry |
| `token_types` | Token type definitions (prompt_tokens, completion_tokens, etc.) |
| `token_prices` | Billing prices (per-1000-token with valid_from dates) |
| `jobs` | Async job tracking |
| `request_events` | Scheduling monitoring events |

The `process.settings` JSONB field can store per-process configuration (e.g., rate limits: `rate_limit_rpm`, `rate_limit_tpm`).

## Adding New Features — Checklist

### Adding a new API endpoint
1. Add the route handler to `src/logos/main.py` (or create a new router and include it)
2. Add any new Pydantic request models to `src/logos/dbutils/dbrequest.py`
3. Add DB operations to `src/logos/dbutils/dbmanager.py`
4. Write unit tests in `tests/unit/`
5. Update `db/init.sql` if schema changes are needed
6. Create a migration in `db/migrations/` (next sequential number)

### Adding a database migration
1. Create `db/migrations/NNN_description.sql` (next number in sequence; currently up to 019)
2. Use `ALTER TABLE` / `CREATE TABLE` — migrations must be idempotent where possible (`IF NOT EXISTS`)
3. **CRITICAL**: Add the migration filename to the `MIGRATIONS` array in `db/migrations/run_all_migrations.sh` — forgetting this means existing deployments never get the migration applied
4. Update `db/init.sql` to reflect the new schema for fresh installs
5. Update ORM models in `dbmodules.py` if applicable
6. For critical columns, also add them to the `_REQUIRED_COLUMNS` list in `dbmanager.py` (defense-in-depth — `ensure_schema()` auto-applies `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` on startup)

**Common migration pitfall**: The `init.sql` file is only executed on first database initialization (PostgreSQL `docker-entrypoint-initdb.d`). Existing deployments with persistent volumes rely entirely on `run_all_migrations.sh` to get schema updates.

### Testing
```bash
# Run unit tests only
./run_tests.sh unit

# Run with Poetry directly
poetry run pytest tests/unit -v

# Run specific test file
poetry run pytest tests/unit/main/test_route_and_execute.py -v
```

Tests stub heavy dependencies (sentence_transformers, gRPC) via `conftest.py`. DBManager should be monkeypatched in tests — never connect to a real database in unit tests.

**Note**: All unit tests should pass on `main` (25 passed, 1 skipped). The skipped test (`test_classification.py`) requires real `sentence-transformers` which is stubbed in `conftest.py`. Tests use `asyncio_mode = "auto"` so `@pytest.mark.asyncio` decorators are NOT needed on test functions.

## Git Workflow & Pull Requests

### Naming Conventions (MANDATORY)

**PR Title** — Must match this regex (enforced by CI):
```
^`(Development|General|Athena|Atlas|AtlasML|Iris|Logos|Nebula|Memiris)`:\s[A-Z].*$
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
3. Run ALL existing tests to verify zero regressions: `poetry run pytest tests/unit/ -v`
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
| GET | `/v1/models` | Profile | List accessible models |

## Testing
- Added N tests in `tests/unit/...`
- Run: `poetry run pytest tests/unit/ -v`

## Database Changes
- Migration: `db/migrations/NNN_description.sql`
```

### Post-PR Checklist
After creating a PR, always verify:
1. **Title validation passes** — check with `gh pr checks <NUMBER>` or view on GitHub
2. **All CI checks pass** — build, lint, tests
3. **No merge conflicts** — rebase on main if needed
4. If any check fails, fix immediately — do NOT leave failing PRs

## Conventions

- **Imports**: Use absolute imports from `logos.*` (e.g., `from logos.auth import authenticate_logos_key`)
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
cd logos && poetry install

# Run locally
poetry run uvicorn logos.main:app --host 0.0.0.0 --port 8000

# Run with Docker
docker compose up --build

# Database is at logos-db:5432/logosdb (user: postgres, pass: root)
```

## Important Notes for AI Agents

1. **main.py is large** (~1690+ lines). Read specific sections rather than the whole file. Use grep to find relevant routes/functions.
2. **DBManager is the critical class** for all database operations. It auto-commits on exit.
3. **No Alembic** — migrations are plain SQL files. Apply via `run_all_migrations.sh` (uses `docker exec`) or run manually. `ensure_schema()` in `dbmanager.py` auto-adds critical missing columns at startup as a safety net.
4. **Provider types**: `cloud` (Azure/OpenAI), `ollama` (local Ollama instances)
5. **Token tracking exists** in the `usage_tokens` and `token_prices` tables.
6. **The `process` table is the key auth entity** — each process has a unique `logos_key`.
7. **Profiles control model access** — `profile_model_permissions` links profiles to models.
8. **Existing tests mock DBManager** — follow the same pattern for new tests.
9. **When adding OpenAI-compatible endpoints** (like `/v1/models`), follow the OpenAI API spec exactly.
10. **For schema changes**: update BOTH `db/init.sql` (fresh install) AND add a migration file AND add the migration to `run_all_migrations.sh` MIGRATIONS array.
11. **DB method return values**: Methods returning `(dict, int)` tuples must be unpacked in endpoints — use `JSONResponse(content=result, status_code=status)`, never return the tuple directly.
12. **Route ordering matters**: FastAPI matches routes in definition order. Specific routes must come before catch-all routes like `/v1/{path:path}`.
13. **Docker build**: Uses multi-stage build with `uv` (pinned version) for fast dependency installation. Runtime stage uses slim Python image with `VIRTUAL_ENV=/opt/venv`.
14. **`process.settings` JSONB**: Flexible per-process config store. Used for rate limits and other settings. No schema migration needed to add new keys.
15. **Traefik routing**: Domain and cert resolver are configured via environment variables `LOGOS_DOMAIN` (default: `localhost`) and `LOGOS_CERT_RESOLVER` (default: empty = no ACME). See `.env.example` for production setup.
16. **Shared dependency**: The `shared/` sibling directory is symlinked as `logos/shared` for local dev. In CI, this is done explicitly: `ln -s ../shared logos/shared`.
17. **Schema drift**: `init.sql` and `dbmodules.py` have some columns that are out of sync (e.g., several `providers` columns exist in SQL but not in ORM). The SQL schema (`init.sql`) is the source of truth; `dbmodules.py` only maps columns that the application code actively uses.
18. **CI caching**: The CI workflow caches Poetry dependencies using `cache: "poetry"` with `cache-dependency-path: logos/poetry.lock`. Always commit `poetry.lock` changes.
