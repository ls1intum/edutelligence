# AGENTS.md — Logos Project Guide for AI Agents

## Project Overview

**Logos** is an LLM Engineering Platform that acts as an intelligent proxy between LLM consumers and multiple LLM providers (Azure, Ollama, OpenAI). It provides usage logging, billing, central resource management, policy-based model selection, scheduling, and monitoring.

## Tech Stack

- **Language**: Python 3.13
- **Framework**: FastAPI (0.115.9) + Uvicorn
- **Database**: PostgreSQL 17 via SQLAlchemy 2.x (raw SQL with `text()`, NOT the ORM query API)
- **HTTP Client**: httpx (async)
- **Dependency Management**: Poetry 2.x
- **Testing**: pytest + pytest-asyncio
- **Containerization**: Docker + Docker Compose + Traefik

## Repository Structure

```
logos/
├── AGENTS.md                          # This file
├── pyproject.toml                     # Poetry config + dependencies
├── Dockerfile                         # Container build
├── docker-compose.yaml                # Full stack (db, app, ui, traefik)
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
│   │   ├── dbmanager.py               # All DB operations (~2148 lines) — context manager pattern
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
1. Create `db/migrations/NNN_description.sql` (next number in sequence; currently up to 014)
2. Use `ALTER TABLE` / `CREATE TABLE` — migrations must be idempotent where possible (`IF NOT EXISTS`)
3. Update `db/init.sql` to reflect the new schema for fresh installs
4. Update ORM models in `dbmodules.py` if applicable

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

**Note**: There are 5 pre-existing test failures on `main` (stale test signatures in `test_execute_modes.py` / `test_route_and_execute.py`, and a missing ML model in `test_classification.py`). These are not caused by new changes.

## Git Workflow & Pull Requests

### Branch Naming
- `feature/logos/description-of-feature` or `feature/logos/issue-NNN`
- Examples: `feature/logos/v1-models-endpoint`, `feature/logos/temp-providers`

### ALWAYS Create Pull Requests for Issues
When implementing a feature for a GitHub issue:
1. Create a feature branch from `main`: `git checkout -b feature/logos/short-description`
2. Implement the feature with tests
3. Run ALL existing tests to verify zero regressions: `poetry run pytest tests/unit/ -v`
4. Commit with a descriptive message: `feat(logos): description (#issue_number)`
5. Push the branch: `git push origin feature/logos/short-description`
6. **Create a PR** with `gh pr create` including:
   - `Closes #NNN` to link the issue
   - Summary of changes
   - List of new/modified files
   - New endpoints documented (method, path, auth, request/response)
   - Testing section (what tests added, how to run)
   - Any database migration notes
7. Never merge directly to `main` without a PR

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
3. **No Alembic** — migrations are plain SQL files run manually via `docker exec`.
4. **Provider types**: `cloud` (Azure/OpenAI), `ollama` (local Ollama instances)
5. **Token tracking exists** in the `usage_tokens` and `token_prices` tables.
6. **The `process` table is the key auth entity** — each process has a unique `logos_key`.
7. **Profiles control model access** — `profile_model_permissions` links profiles to models.
8. **Existing tests mock DBManager** — follow the same pattern for new tests.
9. **When adding OpenAI-compatible endpoints** (like `/v1/models`), follow the OpenAI API spec exactly.
10. **For schema changes**: update BOTH `db/init.sql` (fresh install) AND add a migration file.
11. **DB method return values**: Methods returning `(dict, int)` tuples must be unpacked in endpoints — use `JSONResponse(content=result, status_code=status)`, never return the tuple directly.
12. **Route ordering matters**: FastAPI matches routes in definition order. Specific routes must come before catch-all routes like `/v1/{path:path}`.
13. **Pre-existing test failures**: 5 tests on `main` are known to fail — don't try to fix them unless explicitly asked.
14. **`process.settings` JSONB**: Flexible per-process config store. Used for rate limits and other settings. No schema migration needed to add new keys.
